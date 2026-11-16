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
OBJECT_EXT_RE <- "\\.(rds|qs|qs2|h5seurat|rdata|rda|robj)(\\.gz)?$"

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

  # `skip` keeps a dataset off the site but still builds it; `exclude` is for
  # files that are not datasets at all -- a saved raw count matrix sitting
  # beside the RaceID object built from it, say -- which would otherwise fail
  # stage 1 on every run. Applied after the keys are derived so dropping one
  # file cannot rename its siblings.
  excluded <- tryCatch(as.character(load_config()$exclude), error = function(e) character(0))
  if (length(excluded)) {
    hit <- intersect(names(out), excluded)
    if (length(hit)) {
      log_msg("excluded by config: ", paste(hit, collapse = ", "))
      out <- out[setdiff(names(out), hit)]
    }
  }
  out
}

# --- object loading ----------------------------------------------------------

read_object <- function(path) {
  ext <- tolower(regmatches(basename(path),
                            regexpr(OBJECT_EXT_RE, basename(path), ignore.case = TRUE)))
  ext <- sub("\\.gz$", "", ext)
  if (ext == ".rds") {
    obj <- readRDS(path)
    return(if (inherits(obj, "SCseq")) raceid_to_seurat(obj) else maybe_update_seurat(obj))
  }
  if (ext == ".qs")  { suppressPackageStartupMessages(library(qs));  return(qs::qread(path))  }
  if (ext == ".qs2") { suppressPackageStartupMessages(library(qs2)); return(qs2::qs_read(path)) }
  if (ext == ".h5seurat") {
    suppressPackageStartupMessages(library(SeuratDisk))
    return(maybe_update_seurat(SeuratDisk::LoadH5Seurat(path, verbose = FALSE)))
  }
  if (ext %in% c(".rdata", ".rda", ".robj")) {
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
      is_seurat <- is_seurat | vapply(nms, function(n) inherits(get(n, envir = e), "SCseq"),
                                    logical(1))
  if (!any(is_seurat)) stop("No Seurat or RaceID object in ", basename(path),
                              " (contains: ", paste(nms, collapse = ", "), ")")
    hits <- nms[is_seurat]
    if (length(hits) > 1) {
      sizes <- vapply(hits, function(n) as.numeric(utils::object.size(get(n, envir = e))), 0)
      hits <- hits[order(sizes, decreasing = TRUE)]
      log_msg("note: ", basename(path), " holds ", length(hits),
              " Seurat objects (", paste(nms[is_seurat], collapse = ", "), "); using ", hits[1])
    }
    obj <- get(hits[1], envir = e)
    return(if (inherits(obj, "SCseq")) raceid_to_seurat(obj) else maybe_update_seurat(obj))
  }
  stop("Unsupported extension: ", ext)
}


# Objects saved by older Seurat versions lack slots the current class expects
# (`images` was added in v3.2), and accessing them errors rather than returning
# NULL. Update those on load; leave current objects untouched.
maybe_update_seurat <- function(obj) {
  if (!inherits(obj, "Seurat")) return(obj)
  ok <- tryCatch({ obj@images; TRUE }, error = function(e) FALSE)
  if (ok) return(obj)
  log_msg("object predates the current Seurat class; running UpdateSeuratObject()")
  suppressPackageStartupMessages(library(Seurat))
  suppressWarnings(Seurat::UpdateSeuratObject(obj))
}

# --- RaceID -----------------------------------------------------------------

# RaceID stores its results in an S4 SCseq object rather than a Seurat object.
# Convert on load so the rest of the pipeline is unaware of the difference.
#
# Two details matter. `ndata` holds normalised *fractions* (they sum to 1 per
# cell), so they are scaled back to counts by RaceID's own factor before the log
# transform -- otherwise every value lands in [0, 0.4] and the colour scale is
# meaningless. And `expdata` retains cells that filtering later removed, so the
# raw counts are subset to the cells `ndata` actually kept.

# The 2017-19 CEL-Seq reference used in this lab names features
# `SYMBOL__chrN`, and joins multi-mapped symbols with `|`
# (`ABHD14A-ACY1__chr3|ACY1__chr3`). Left alone those reach the gene picker
# verbatim, so the suffix is dropped and multi-mapped entries keep their first
# symbol, which puts these objects on the same footing as the newer RaceID
# datasets that already carry bare symbols.
#
# The `_` -> `-` substitution is not cosmetic: CreateSeuratObject() applies it
# itself, so a `data` layer added afterwards under the original names shares no
# feature with the object and SetAssayData() fails outright. Doing it here, once,
# keeps both layers on one set of names.
clean_raceid_features <- function(g) {
  g <- sub("\\|.*$", "", g)            # multi-mapped: keep the first symbol
  g <- sub("__chr[^_|]*$", "", g)      # drop the reference's chromosome suffix
  g <- gsub("[_|]", "-", g)            # Seurat forbids both in feature names
  make.unique(g)                       # same symbol on two chromosomes
}

raceid_to_seurat <- function(sc) {
  suppressPackageStartupMessages({ library(Seurat); library(SeuratObject); library(Matrix) })
  nd <- slot(sc, "ndata")
  cells <- colnames(nd)
  ed <- slot(sc, "expdata")
  ed <- ed[rownames(nd), intersect(cells, colnames(ed)), drop = FALSE]
  if (!identical(colnames(ed), cells)) {
    log_msg("RaceID: expdata covers ", ncol(ed), "/", length(cells),
            " of the retained cells; using ndata cells only")
    cells <- colnames(ed)
    nd <- nd[, cells, drop = FALSE]
  }

  totals <- tryCatch(as.numeric(slot(sc, "counts")), error = function(e) numeric(0))
  sf <- if (length(totals)) min(totals[totals > 0]) else 1
  dat <- nd * sf
  # RaceID writes ndata as either a dgCMatrix or a base matrix depending on
  # version; only the sparse one has an @x slot to transform in place.
  if (methods::is(dat, "sparseMatrix")) dat@x <- log1p(dat@x) else dat <- log1p(dat)
  if (!methods::is(ed, "sparseMatrix")) ed <- methods::as(as.matrix(ed), "dgCMatrix")
  # Older RaceID versions store ndata as a data.frame. Seurat keeps whatever it
  # is handed, and stage 2's dense-to-sparse conversion cannot coerce a
  # data.frame ("invalid type 'list'"), so settle the type here instead.
  if (!methods::is(dat, "sparseMatrix")) dat <- methods::as(as.matrix(dat), "dgCMatrix")
  log_msg("RaceID: ", nrow(nd), " genes x ", length(cells),
          " cells; ndata rescaled by ", format(round(sf)), " then log1p")

  features <- clean_raceid_features(rownames(nd))
  if (!identical(features, rownames(nd))) {
    n_renamed <- sum(features != rownames(nd))
    log_msg("RaceID: normalised ", n_renamed, "/", length(features), " feature names (e.g. ",
            rownames(nd)[which(features != rownames(nd))[1]], " -> ",
            features[which(features != rownames(nd))[1]], ")")
    rownames(ed) <- features
    rownames(dat) <- features
  }

  obj <- CreateSeuratObject(counts = ed, project = "raceid")
  obj <- SetAssayData(obj, assay = "RNA", layer = "data", new.data = dat)

  # Cluster partition, and the palette RaceID assigned to it.
  cpart <- slot(sc, "cpart")
  colours <- list()
  if (length(cpart)) {
    cl <- as.character(cpart[cells])
    obj$cluster <- factor(cl, levels = as.character(sort(unique(as.integer(cl)))))
    fcol <- tryCatch(slot(sc, "fcol"), error = function(e) character(0))
    if (length(fcol)) {
      ids <- as.integer(levels(obj$cluster))
      ok <- ids >= 1 & ids <= length(fcol)
      if (any(ok)) colours$cluster <- as.list(stats::setNames(fcol[ids[ok]],
                                                              as.character(ids[ok])))
    }
  }

  # Cell names carry the sample: P1_CNV_3d_1_2 -> P1_CNV_3d_1, P212_A10 -> P212.
  for (pat in c("_[0-9]+$", "_[A-Z][0-9]+$")) {
    cand <- sub(pat, "", cells)
    n <- length(unique(cand))
    if (n >= 2 && n <= 100 && n < length(cells)) { obj$sample <- cand; break }
  }
  if (length(totals) == length(cells)) obj$total_counts_raceid <- as.numeric(totals)

  # Whichever 2-D layouts this RaceID version stored and that match the cells.
  for (s in c("umap", "tsne", "fr")) {
    if (!(.hasSlot(sc, s))) next
    m <- tryCatch(slot(sc, s), error = function(e) NULL)
    if (is.null(m) || !is.matrix(as.matrix(m)) || nrow(m) != length(cells) || ncol(m) < 2) next
    m <- as.matrix(m)[, 1:2, drop = FALSE]
    rownames(m) <- cells
    colnames(m) <- paste0(s, "_", 1:2)
    obj[[s]] <- SeuratObject::CreateDimReducObject(embeddings = m, key = paste0(s, "_"),
                                                   assay = "RNA")
  }
  if (!length(SeuratObject::Reductions(obj)))
    log_msg("RaceID: WARNING no 2-D layout matches the retained cells")

  obj@misc <- c(obj@misc, list(raceid_colours = colours))
  obj
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
