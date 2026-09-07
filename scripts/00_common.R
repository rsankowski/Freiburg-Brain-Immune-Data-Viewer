# Shared helpers for the Seurat -> AnnData-Zarr pipeline.
# Sourced by every R stage. No side effects beyond creating build dirs.

suppressPackageStartupMessages(library(jsonlite))

`%||%` <- function(a, b) if (is.null(a)) b else a

# --- paths -------------------------------------------------------------------

find_root <- function() {
  # Walk up from the working directory until we see data/ and scripts/.
  d <- normalizePath(getwd(), mustWork = TRUE)
  repeat {
    if (dir.exists(file.path(d, "scripts")) && dir.exists(file.path(d, "data"))) return(d)
    parent <- dirname(d)
    if (parent == d) stop("Could not locate project root (needs scripts/ and data/).")
    d <- parent
  }
}

ROOT       <- find_root()
DATA_DIR   <- file.path(ROOT, "data")
BUILD_DIR  <- file.path(ROOT, "build")
LOG_DIR    <- file.path(BUILD_DIR, "logs")
INV_DIR    <- file.path(BUILD_DIR, "inventory")
MANIFEST   <- file.path(BUILD_DIR, "manifest.json")
FAILURES   <- file.path(BUILD_DIR, "failures.json")

ensure_dirs <- function() {
  for (d in c(BUILD_DIR, LOG_DIR, INV_DIR)) dir.create(d, showWarnings = FALSE, recursive = TRUE)
}

# --- logging -----------------------------------------------------------------

log_msg <- function(...) {
  cat(sprintf("[%s] %s\n", format(Sys.time(), "%H:%M:%S"), paste0(..., collapse = "")))
  flush(stdout())
}

# --- CLI ---------------------------------------------------------------------

# Minimal parser so we do not depend on optparse.
# Supports --key value, --key=value and boolean flags.
parse_args <- function(args = commandArgs(trailingOnly = TRUE)) {
  out <- list()
  i <- 1
  while (i <= length(args)) {
    a <- args[[i]]
    if (!startsWith(a, "--")) { i <- i + 1; next }
    a <- sub("^--", "", a)
    if (grepl("=", a, fixed = TRUE)) {
      k <- sub("=.*$", "", a); v <- sub("^[^=]*=", "", a)
      out[[k]] <- v; i <- i + 1
    } else if (i < length(args) && !startsWith(args[[i + 1]], "--")) {
      out[[a]] <- args[[i + 1]]; i <- i + 2
    } else {
      out[[a]] <- TRUE; i <- i + 1
    }
  }
  out
}

flag <- function(opts, name) isTRUE(opts[[name]]) || identical(opts[[name]], "true")

# --- dataset discovery -------------------------------------------------------

slugify <- function(x) {
  x <- tolower(x)
  x <- gsub("[^a-z0-9]+", "_", x)
  gsub("^_+|_+$", "", x)
}

# Walk data/ recursively for serialised objects and derive a stable key from
# the path relative to data/. Directory components are joined with "__"; the
# file stem is appended only when a directory holds more than one object
# (otherwise the directory alone names the dataset).
OBJECT_EXT_RE <- "\\.(rds|qs|qs2|h5seurat|rdata|rda)(\\.gz)?$"

discover_datasets <- function(data_dir = DATA_DIR) {
  files <- list.files(
    data_dir,
    pattern = OBJECT_EXT_RE,
    recursive = TRUE, full.names = TRUE, ignore.case = TRUE
  )
  files <- files[!grepl("(^|/)\\._", files)]           # macOS resource forks
  files <- sort(files)
  if (!length(files)) return(list())

  rel <- sub(paste0("^", gsub("([.\\^$|()*+?{}\\[\\]])", "\\\\\\1", data_dir), "/"), "", files)
  dirs <- dirname(rel)
  dirs[dirs == "."] <- ""
  stems <- sub(OBJECT_EXT_RE, "", basename(rel), ignore.case = TRUE)
  multi <- dirs %in% names(which(table(dirs) > 1))

  out <- list()
  for (i in seq_along(files)) {
    comps <- if (nzchar(dirs[i])) strsplit(dirs[i], "/", fixed = TRUE)[[1]] else character(0)
    if (multi[i] || !length(comps)) comps <- c(comps, stems[i])
    key <- paste(vapply(comps, slugify, ""), collapse = "__")
    out[[key]] <- list(
      key             = key,
      path            = unname(files[i]),
      rel_path        = unname(rel[i]),
      paper_id        = if (length(strsplit(dirs[i], "/", fixed = TRUE)[[1]])) strsplit(dirs[i], "/", fixed = TRUE)[[1]][1] else NA_character_,
      file_stem       = unname(stems[i]),
      format          = tolower(sub("^.*?", "", regmatches(basename(files[i]),
                          regexpr(OBJECT_EXT_RE, basename(files[i]), ignore.case = TRUE)))),
      file_size_bytes = unname(as.numeric(file.info(files[i])$size))
    )
  }
  out
}

# --- object loading ----------------------------------------------------------

read_object <- function(path) {
  ext <- tolower(regmatches(basename(path),
                            regexpr(OBJECT_EXT_RE, basename(path), ignore.case = TRUE)))
  ext <- sub("\\.gz$", "", ext)
  if (ext == ".rds") return(readRDS(path))
  if (ext == ".qs")  { suppressPackageStartupMessages(library(qs));  return(qs::qread(path))  }
  if (ext == ".qs2") { suppressPackageStartupMessages(library(qs2)); return(qs2::qs_read(path)) }
  if (ext == ".h5seurat") {
    suppressPackageStartupMessages(library(SeuratDisk))
    return(SeuratDisk::LoadH5Seurat(path, verbose = FALSE))
  }
  if (ext %in% c(".rdata", ".rda")) {
    # load() peels a single layer of gzip on its own. Some of these files are
    # gzipped twice (an already-compressed .RData that was then gzipped again),
    # which leaves gzip bytes where load() expects the serialisation magic --
    # gzcon() over the connection strips the second layer.
    e <- new.env(parent = emptyenv())
    nms <- tryCatch(load(path, envir = e), error = function(err) {
      log_msg("load() failed (", conditionMessage(err), "); retrying through gzcon()")
      con <- gzcon(gzfile(path, "rb"))
      on.exit(close(con), add = TRUE)
      load(con, envir = e)
    })
    is_seurat <- vapply(nms, function(n) inherits(get(n, envir = e), "Seurat"), logical(1))
    if (!any(is_seurat)) stop("No Seurat object in ", basename(path),
                              " (contains: ", paste(nms, collapse = ", "), ")")
    hits <- nms[is_seurat]
    if (length(hits) > 1) {
      sizes <- vapply(hits, function(n) as.numeric(utils::object.size(get(n, envir = e))), 0)
      hits <- hits[order(sizes, decreasing = TRUE)]
      log_msg("note: ", basename(path), " holds ", length(hits),
              " Seurat objects (", paste(nms[is_seurat], collapse = ", "), "); using ", hits[1])
    }
    return(get(hits[1], envir = e))
  }
  stop("Unsupported extension: ", ext)
}

# --- json --------------------------------------------------------------------

write_json_atomic <- function(x, path) {
  tmp <- paste0(path, ".tmp")
  write(jsonlite::toJSON(x, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null"), tmp)
  file.rename(tmp, path)
  invisible(path)
}

read_json_if_exists <- function(path) {
  if (!file.exists(path)) return(NULL)
  jsonlite::fromJSON(path, simplifyVector = FALSE)
}

# Append a failure record; never throws.
record_failure <- function(stage, dataset, err, traceback = NULL) {
  ensure_dirs()
  cur <- read_json_if_exists(FAILURES) %||% list()
  cur[[length(cur) + 1]] <- list(
    stage = stage, dataset = dataset,
    error = as.character(err),
    traceback = traceback,
    time = format(Sys.time(), "%Y-%m-%dT%H:%M:%S%z")
  )
  write_json_atomic(cur, FAILURES)
}

rss_mb <- function(pid = Sys.getpid()) {
  v <- suppressWarnings(system2("ps", c("-o", "rss=", "-p", pid), stdout = TRUE, stderr = FALSE))
  if (!length(v)) return(NA_real_)
  as.numeric(trimws(v[1])) / 1024
}

# Stable md5 of a character vector, without pulling in digest/openssl.
md5_of_chars <- function(x) {
  tmp <- tempfile()
  on.exit(unlink(tmp), add = TRUE)
  writeLines(as.character(x), tmp)
  unname(tools::md5sum(tmp))
}

# --- config ------------------------------------------------------------------

CONFIG_PATH <- file.path(ROOT, "config", "pipeline.json")

load_config <- function() {
  cfg <- read_json_if_exists(CONFIG_PATH)
  if (is.null(cfg)) stop("Missing config/pipeline.json")
  cfg
}

save_config <- function(cfg) write_json_atomic(cfg, CONFIG_PATH)

# Datasets selected for conversion: everything in the manifest minus entries
# the config marks as skip/duplicate, intersected with --dataset if given.
select_datasets <- function(cfg, opts, keys = NULL) {
  m <- read_json_if_exists(MANIFEST)
  if (is.null(m)) stop("Missing build/manifest.json — run stage 1 first.")
  all_keys <- names(m$datasets)
  if (is.null(keys) && !is.null(opts$dataset) && !isTRUE(opts$dataset)) {
    keys <- strsplit(as.character(opts$dataset), ",", fixed = TRUE)[[1]]
  }
  sel <- if (is.null(keys)) all_keys else intersect(all_keys, keys)
  if (!flag(opts, "include-duplicates") && is.null(keys)) {
    sel <- Filter(function(k) {
      d <- cfg$datasets[[k]]
      !isTRUE(d$skip) && is.null(d$duplicate_of)
    }, sel)
  }
  if (!length(sel)) stop("No datasets selected.")
  sel
}

# --- generic subprocess driver ----------------------------------------------

# Runs `script --worker --dataset KEY` in a child process, one dataset at a
# time, polling the child's RSS so peak memory is measured rather than guessed.
# Returns a named list of per-dataset status.
run_stage_driver <- function(stage, script, keys, output_for, opts) {
  ensure_dirs()
  rscript <- file.path(R.home("bin"), "Rscript")
  status <- list()
  for (k in keys) {
    out <- output_for(k)
    if (file.exists(out) && !flag(opts, "force")) { log_msg("skip (done): ", k); status[[k]] <- "skipped"; next }
    logf <- file.path(LOG_DIR, sprintf("%s_%s.log", stage, k))
    if (flag(opts, "dry-run")) { log_msg("dry-run: ", k, " -> ", out); status[[k]] <- "dry-run"; next }

    log_msg(stage, ": ", k, " -> build/logs/", basename(logf))
    cmd <- sprintf(
      "%s --vanilla %s --worker --dataset %s >%s 2>&1 & pid=$!; while kill -0 $pid 2>/dev/null; do ps -o rss= -p $pid 2>/dev/null; sleep 2; done; wait $pid",
      shQuote(rscript), shQuote(script), shQuote(k), shQuote(logf))
    t0 <- Sys.time()
    res <- suppressWarnings(system2("/bin/sh", c("-c", shQuote(cmd)), stdout = TRUE, stderr = NULL))
    code <- attr(res, "status") %||% 0
    peak <- suppressWarnings(max(as.numeric(trimws(res)), na.rm = TRUE)) / 1024
    secs <- as.numeric(difftime(Sys.time(), t0, units = "secs"))

    if (!identical(as.integer(code), 0L) || !file.exists(out)) {
      tail_txt <- paste(utils::tail(readLines(logf, warn = FALSE), 40), collapse = "\n")
      log_msg("FAILED: ", k, " (exit ", code, ") — see ", logf)
      record_failure(stage, k, sprintf("worker exited with status %s", code), tail_txt)
      status[[k]] <- "failed"; next                       # continue with next dataset
    }
    log_msg(sprintf("  ok in %.0fs, peak RSS %.1f GB", secs, peak / 1024))
    status[[k]] <- "ok"
  }
  status
}

# Wraps a worker body so failures land in build/failures.json and exit non-zero.
run_worker_guarded <- function(stage, key, fn) {
  ok <- tryCatch({ fn(); TRUE }, error = function(e) {
    log_msg("ERROR: ", conditionMessage(e))
    record_failure(stage, key, conditionMessage(e),
                   paste(utils::capture.output(traceback()), collapse = "\n"))
    FALSE
  })
  quit(status = if (ok) 0 else 1)
}

script_dir <- function() {
  normalizePath(dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1])))
}
