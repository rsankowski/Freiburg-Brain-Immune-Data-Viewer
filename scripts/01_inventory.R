#!/usr/bin/env Rscript
# Stage 1 — inventory.
#
# Driver mode (default): discovers datasets under data/, writes the mapping to
# build/manifest.json immediately, then inspects one dataset at a time in a
# *child* R process so no two objects are ever resident and the OS actually
# reclaims memory between datasets. The parent polls the child's RSS so the
# reported peak is real, not a gc() estimate.
#
# Worker mode (--worker --dataset KEY): loads exactly one object and writes
# build/inventory/<key>.json.
#
#   Rscript scripts/01_inventory.R [--dataset KEY] [--force] [--dry-run] [--discover-only]

suppressWarnings(suppressPackageStartupMessages(
  source(file.path(dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1])), "00_common.R"))
))

opts <- parse_args()
STAGE <- "01_inventory"

# ---------------------------------------------------------------------------
# Inspection of a single Seurat object
# ---------------------------------------------------------------------------

meta_column_summary <- function(md) {
  cols <- list()
  for (nm in colnames(md)) {
    v <- md[[nm]]
    if (is.list(v) && !is.factor(v)) {
      cols[[nm]] <- list(type = "unsupported", class = class(v)[1]); next
    }
    n_missing <- sum(is.na(v))
    if (is.numeric(v) || is.integer(v)) {
      u <- length(unique(v[!is.na(v)]))
      cols[[nm]] <- list(
        type = "numeric", class = class(v)[1], cardinality = u, n_missing = n_missing,
        min = if (u) as.numeric(min(v, na.rm = TRUE)) else NA_real_,
        max = if (u) as.numeric(max(v, na.rm = TRUE)) else NA_real_,
        median = if (u) as.numeric(stats::median(v, na.rm = TRUE)) else NA_real_
      )
    } else {
      v <- as.character(v)
      lev <- unique(v[!is.na(v)])
      cols[[nm]] <- list(
        type = "categorical", class = class(md[[nm]])[1],
        cardinality = length(lev), n_missing = n_missing,
        levels_preview = as.character(utils::head(sort(lev), 25))
      )
    }
  }
  cols
}

assay_summary <- function(obj) {
  out <- list()
  for (a in SeuratObject::Assays(obj)) {
    as_obj <- obj[[a]]
    layers <- tryCatch(SeuratObject::Layers(as_obj), error = function(e) character(0))
    if (!length(layers)) {
      # Seurat v3/v4 Assay: probe the classic slots.
      layers <- names(which(vapply(c("counts", "data", "scale.data"), function(s) {
        m <- tryCatch(methods::slot(as_obj, s), error = function(e) NULL)
        !is.null(m) && prod(dim(m)) > 0
      }, logical(1))))
    }
    out[[a]] <- list(
      class      = class(as_obj)[1],
      n_features = nrow(as_obj),
      n_cells    = ncol(as_obj),
      layers     = as.character(layers),
      key        = tryCatch(SeuratObject::Key(as_obj), error = function(e) NA_character_),
      var_features_n = tryCatch(length(SeuratObject::VariableFeatures(obj, assay = a)),
                                error = function(e) NA_integer_)
    )
  }
  out
}

reduction_summary <- function(obj) {
  out <- list()
  for (r in SeuratObject::Reductions(obj)) {
    emb <- tryCatch(SeuratObject::Embeddings(obj, reduction = r), error = function(e) NULL)
    if (is.null(emb)) next
    out[[r]] <- list(
      n_cells = nrow(emb), n_dims = ncol(emb),
      key     = tryCatch(SeuratObject::Key(obj[[r]]), error = function(e) NA_character_),
      assay   = tryCatch(SeuratObject::DefaultAssay(obj[[r]]), error = function(e) NA_character_),
      is_embedding = grepl("umap|tsne|pca|harmony|scvi|phate", r, ignore.case = TRUE)
    )
  }
  out
}

inspect <- function(obj) {
  suppressPackageStartupMessages({ library(SeuratObject) })
  md <- obj@meta.data
  list(
    object_class  = class(obj)[1],
    seurat_version = tryCatch(as.character(obj@version), error = function(e) NA_character_),
    n_cells       = ncol(obj),
    n_features    = nrow(obj),
    default_assay = SeuratObject::DefaultAssay(obj),
    assays        = assay_summary(obj),
    reductions    = reduction_summary(obj),
    graphs        = as.character(tryCatch(names(obj@graphs), error = function(e) character(0))),
    commands      = as.character(tryCatch(names(obj@commands), error = function(e) character(0))),
    meta_columns  = meta_column_summary(md),
    n_meta_columns = ncol(md),
    # Fingerprints let us tell apart genuinely different datasets from
    # re-exports of the same cells under a different filename.
    fingerprint   = list(
      cells_md5    = md5_of_chars(colnames(obj)),
      features_md5 = md5_of_chars(rownames(obj)),
      umap_md5     = tryCatch(
        md5_of_chars(apply(round(SeuratObject::Embeddings(obj, "umap"), 4), 1, paste, collapse = ",")),
        error = function(e) NA_character_)
    )
  )
}

# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

run_worker <- function(key) {
  # Load Seurat before the object rather than on demand. Loading it afterwards
  # can fail while initialising RcppAnnoy's modules ("attempt to apply
  # non-function"); the later stages never hit this because they attach Seurat
  # at start-up.
  suppressWarnings(suppressPackageStartupMessages(
    tryCatch(library(Seurat), error = function(e)
      log_msg("note: Seurat not attached up front (", conditionMessage(e), ")"))))
  ds <- discover_datasets()[[key]]
  if (is.null(ds)) stop("Unknown dataset key: ", key)
  log_msg("worker: ", key, "  <- ", ds$rel_path)
  gc(reset = TRUE, full = TRUE)
  rss_before <- rss_mb()

  t0 <- Sys.time()
  obj <- read_object(ds$path)
  load_secs <- as.numeric(difftime(Sys.time(), t0, units = "secs"))
  rss_loaded <- rss_mb()
  log_msg(sprintf("loaded in %.1fs; RSS %.0f MB (delta %.0f MB)",
                  load_secs, rss_loaded, rss_loaded - rss_before))

  info <- inspect(obj)
  info$load_seconds <- round(load_secs, 1)
  info$rss_mb_after_load <- round(rss_loaded, 1)
  info$object_size_mb <- tryCatch(round(as.numeric(utils::object.size(obj)) / 1024^2, 1),
                                  error = function(e) NA_real_)
  g <- gc(full = TRUE)
  info$gc_max_used_mb <- round(sum(g[, "max used"] * c(56, 8)) / 1024^2, 1)

  rm(obj); gc(full = TRUE)

  out <- c(ds, list(inventory = info,
                    inventoried_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%S%z")))
  write_json_atomic(out, file.path(INV_DIR, paste0(key, ".json")))
  log_msg("wrote ", file.path("build/inventory", paste0(key, ".json")))
  invisible(TRUE)
}

# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

assemble_manifest <- function(datasets) {
  for (k in names(datasets)) {
    p <- file.path(INV_DIR, paste0(k, ".json"))
    if (file.exists(p)) {
      j <- read_json_if_exists(p)
      datasets[[k]]$inventory <- j$inventory
      datasets[[k]]$inventoried_at <- j$inventoried_at
    }
  }
  manifest <- list(
    schema_version = 1,
    stage = STAGE,
    generated_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%S%z"),
    data_root = DATA_DIR,
    r_version = paste(R.version$major, R.version$minor, sep = "."),
    seurat_version = tryCatch(as.character(packageVersion("Seurat")), error = function(e) NA_character_),
    n_datasets = length(datasets),
    datasets = datasets
  )
  write_json_atomic(manifest, MANIFEST)
  manifest
}

run_driver <- function() {
  ensure_dirs()
  datasets <- discover_datasets()
  if (!length(datasets)) stop("No .rds/.qs/.qs2 files found under ", DATA_DIR)

  log_msg("discovered ", length(datasets), " dataset(s):")
  for (k in names(datasets)) {
    log_msg(sprintf("  %-46s %6.1f GB  %s", k,
                    datasets[[k]]$file_size_bytes / 1024^3, datasets[[k]]$rel_path))
  }
  assemble_manifest(datasets)          # mapping on disk before any object is opened
  log_msg("wrote build/manifest.json (mapping only)")

  if (flag(opts, "discover-only")) return(invisible(TRUE))

  targets <- names(datasets)
  if (!is.null(opts$dataset) && !isTRUE(opts$dataset)) {
    targets <- intersect(targets, strsplit(as.character(opts$dataset), ",", fixed = TRUE)[[1]])
    if (!length(targets)) stop("--dataset matched nothing")
  }

  self <- normalizePath(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1]))
  rscript <- file.path(R.home("bin"), "Rscript")

  for (k in targets) {
    done <- file.exists(file.path(INV_DIR, paste0(k, ".json")))
    if (done && !flag(opts, "force")) { log_msg("skip (done): ", k); next }
    logf <- file.path(LOG_DIR, sprintf("%s_%s.log", STAGE, k))
    if (flag(opts, "dry-run")) { log_msg("dry-run: would inventory ", k, " -> ", logf); next }

    log_msg("inventory: ", k, " (", sprintf("%.1f", datasets[[k]]$file_size_bytes / 1024^3),
            " GB on disk) -> build/logs/", basename(logf))
    # Child in its own process; parent samples the child's RSS every 2s.
    cmd <- sprintf(
      "%s --vanilla %s --worker --dataset %s >%s 2>&1 & pid=$!; while kill -0 $pid 2>/dev/null; do ps -o rss= -p $pid 2>/dev/null; sleep 2; done; wait $pid",
      shQuote(rscript), shQuote(self), shQuote(k), shQuote(logf))
    t0 <- Sys.time()
    res <- suppressWarnings(system2("/bin/sh", c("-c", shQuote(cmd)), stdout = TRUE, stderr = NULL))
    status <- attr(res, "status") %||% 0
    peak <- suppressWarnings(max(as.numeric(trimws(res)), na.rm = TRUE)) / 1024
    elapsed <- as.numeric(difftime(Sys.time(), t0, units = "secs"))

    if (!identical(as.integer(status), 0L) || !file.exists(file.path(INV_DIR, paste0(k, ".json")))) {
      tail_txt <- paste(utils::tail(readLines(logf, warn = FALSE), 30), collapse = "\n")
      log_msg("FAILED: ", k, " (exit ", status, ") — see ", logf)
      record_failure(STAGE, k, sprintf("worker exited with status %s", status), tail_txt)
      next
    }
    log_msg(sprintf("  ok in %.0fs, peak RSS %.1f GB", elapsed, peak / 1024))

    # Fold the measured peak into the per-dataset record.
    p <- file.path(INV_DIR, paste0(k, ".json"))
    j <- read_json_if_exists(p)
    j$inventory$peak_rss_mb <- round(peak, 1)
    j$inventory$wall_seconds <- round(elapsed, 1)
    write_json_atomic(j, p)
  }

  m <- assemble_manifest(datasets)
  log_msg("wrote build/manifest.json with ",
          sum(vapply(m$datasets, function(d) !is.null(d$inventory), logical(1))),
          "/", length(m$datasets), " datasets inventoried")
  invisible(TRUE)
}

if (flag(opts, "worker")) {
  key <- as.character(opts$dataset)
  ok <- tryCatch({ run_worker(key); TRUE },
                 error = function(e) {
                   log_msg("ERROR: ", conditionMessage(e))
                   record_failure(STAGE, key, conditionMessage(e),
                                  paste(utils::capture.output(traceback()), collapse = "\n"))
                   FALSE
                 })
  quit(status = if (ok) 0 else 1)
} else {
  run_driver()
}
