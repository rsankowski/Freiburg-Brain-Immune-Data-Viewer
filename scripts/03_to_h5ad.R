#!/usr/bin/env Rscript
# Stage 3 — trimmed Seurat object -> .h5ad.
#
# Writer chain: anndataR if installed, else sceasy, else a direct reticulate
# writer. Whichever runs, the result is verified against the source object
# before the file is accepted: dims, embedding shapes and 100 random expression
# values must match, or the stage fails loudly and leaves no output behind.
#
#   Rscript scripts/03_to_h5ad.R [--dataset KEY] [--force] [--writer anndataR|sceasy|direct]

suppressWarnings(suppressPackageStartupMessages(
  source(file.path(dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1])), "00_common.R"))
))

opts      <- parse_args()
STAGE     <- "03_to_h5ad"
TRIM_DIR  <- file.path(BUILD_DIR, "trimmed")
H5AD_DIR  <- file.path(BUILD_DIR, "h5ad")
CHECK_DIR <- file.path(BUILD_DIR, "checks")
h5ad_out  <- function(k) file.path(H5AD_DIR, paste0(k, ".h5ad"))
# Override with PIPELINE_VENV_PYTHON when the venv is not inside the project
# (the self-test runs the stages from a sandbox directory).
VENV_PY   <- Sys.getenv("PIPELINE_VENV_PYTHON",
                        unset = file.path(ROOT, ".venv", "bin", "python"))

# obsm keys must be X_-prefixed and free of dots for Vitessce/scanpy.
obsm_key <- function(reduction) paste0("X_", gsub("[^a-z0-9]+", "_", tolower(reduction)))

setup_python <- function() {
  suppressPackageStartupMessages(library(reticulate))
  if (!file.exists(VENV_PY)) stop("Missing ", VENV_PY, " — create the venv first.")
  Sys.setenv(RETICULATE_PYTHON = VENV_PY)
  reticulate::use_python(VENV_PY, required = TRUE)
  invisible(TRUE)
}

# --- writers -----------------------------------------------------------------

write_direct <- function(obj, path) {
  setup_python()
  suppressPackageStartupMessages({ library(reticulate); library(Matrix); library(SeuratObject) })
  ad <- import("anndata", convert = FALSE)
  np <- import("numpy", convert = FALSE)
  pd <- import("pandas", convert = FALSE)

  X <- Matrix::t(LayerData(obj, assay = "RNA", layer = "data"))   # cells x genes
  log_msg(sprintf("X: %d cells x %d genes, %.0fM non-zero", nrow(X), ncol(X), Matrix::nnzero(X) / 1e6))
  Xpy <- r_to_py(X)$tocsr()$astype(np$float32)                    # CSR float32: one row = one cell

  md <- obj@meta.data
  for (nm in names(md)) if (is.factor(md[[nm]])) md[[nm]] <- as.character(md[[nm]])
  obs <- pd$DataFrame(r_to_py(as.list(md)), index = r_to_py(rownames(md)))

  hvg <- obj@misc$hvg %||% character(0)
  var <- pd$DataFrame(r_to_py(list(highly_variable = rownames(obj) %in% hvg)),
                      index = r_to_py(rownames(obj)))

  adata <- ad$AnnData(X = Xpy, obs = obs, var = var)
  for (r in Reductions(obj)) {
    emb <- Embeddings(obj, reduction = r)
    k <- obsm_key(r)
    adata$obsm$`__setitem__`(k, r_to_py(matrix(as.numeric(emb), nrow = nrow(emb)))$astype(np$float32))
    log_msg("  obsm/", k, " <- reduction ", r, " (", nrow(emb), "x", ncol(emb), ")")
  }
  adata$uns$`__setitem__`("dataset_key", obj@misc$dataset_key %||% "")
  adata$uns$`__setitem__`("title", obj@misc$title %||% "")
  adata$write_h5ad(path, compression = "gzip")
  invisible(TRUE)
}

write_sceasy <- function(obj, path) {
  if (!requireNamespace("sceasy", quietly = TRUE)) stop("sceasy not installed")
  setup_python()
  sceasy::convertFormat(obj, from = "seurat", to = "anndata", outFile = path,
                        main_layer = "data", drop_single_values = FALSE)
  invisible(TRUE)
}

write_anndataR <- function(obj, path) {
  if (!requireNamespace("anndataR", quietly = TRUE)) stop("anndataR not installed")
  anndataR::write_h5ad(anndataR::from_Seurat(obj, layers_mapping = c(X = "data")), path)
  invisible(TRUE)
}

# --- verification ------------------------------------------------------------

# Re-read what we wrote and compare it with the object still in memory.
# Everything stays on the Python side (convert = FALSE) so reticulate does not
# silently turn AnnData attributes into R objects that no longer have methods.
verify_h5ad <- function(obj, path, n_sample = 100L) {
  setup_python()
  suppressPackageStartupMessages({ library(reticulate); library(Matrix); library(SeuratObject) })
  ad <- import("anndata", convert = FALSE)
  bi <- import_builtins(convert = FALSE)
  a  <- ad$read_h5ad(path)

  problems <- character(0)
  n_obs  <- as.integer(py_to_r(a$n_obs))
  n_vars <- as.integer(py_to_r(a$n_vars))
  if (n_obs != ncol(obj))  problems <- c(problems, sprintf("n_obs %d != %d cells", n_obs, ncol(obj)))
  if (n_vars != nrow(obj)) problems <- c(problems, sprintf("n_vars %d != %d features", n_vars, nrow(obj)))

  cells <- as.character(py_to_r(a$obs_names$tolist()))
  genes <- as.character(py_to_r(a$var_names$tolist()))
  if (!identical(cells, colnames(obj))) problems <- c(problems, "obs_names differ from colnames(obj)")
  if (!identical(genes, rownames(obj))) problems <- c(problems, "var_names differ from rownames(obj)")

  obsm_keys <- as.character(py_to_r(bi$list(a$obsm$keys())))
  for (r in Reductions(obj)) {
    k <- obsm_key(r)
    if (!(k %in% obsm_keys)) {
      problems <- c(problems, sprintf("missing obsm/%s (found: %s)", k, paste(obsm_keys, collapse = ", ")))
      next
    }
    d_h5  <- as.integer(unlist(py_to_r(a$obsm$`__getitem__`(k)$shape)))
    d_src <- as.integer(dim(Embeddings(obj, reduction = r)))
    if (!identical(d_h5, d_src))
      problems <- c(problems, sprintf("obsm/%s shape %s != %s", k,
                                      paste(d_h5, collapse = "x"), paste(d_src, collapse = "x")))
  }

  var_cols <- as.character(py_to_r(bi$list(a$var$columns)))
  hvg_src  <- sum(rownames(obj) %in% (obj@misc$hvg %||% character(0)))
  hvg_h5   <- if ("highly_variable" %in% var_cols)
                as.integer(py_to_r(a$var$`__getitem__`("highly_variable")$sum())) else NA_integer_
  if (is.na(hvg_h5) || hvg_h5 != hvg_src)
    problems <- c(problems, sprintf("var/highly_variable %s != %d (var columns: %s)",
                                    hvg_h5, hvg_src, paste(var_cols, collapse = ", ")))

  # 100 random expression values compared against the source matrix; half of the
  # sample is forced onto non-zero entries so this is not a comparison of zeros.
  set.seed(42)
  src <- LayerData(obj, assay = "RNA", layer = "data")
  i <- sample.int(ncol(obj), n_sample, replace = TRUE)     # cells
  j <- sample.int(nrow(obj), n_sample, replace = TRUE)     # genes
  half <- n_sample %/% 2
  nz_cell <- sample.int(ncol(obj), 1)
  nz_rows <- which(src[, nz_cell] > 0)
  if (length(nz_rows) >= half) {
    i[seq_len(half)] <- nz_cell
    j[seq_len(half)] <- sample(nz_rows, half)
  }
  want <- as.numeric(src[cbind(j, i)])
  Xpy <- a$X
  got <- vapply(seq_len(n_sample), function(t)
    as.numeric(py_to_r(Xpy$`__getitem__`(tuple(as.integer(i[t] - 1L), as.integer(j[t] - 1L))))), numeric(1))
  bad <- which(abs(want - got) > 1e-4 * pmax(1, abs(want)))
  if (length(bad))
    problems <- c(problems, sprintf("%d/%d sampled expression values differ (e.g. want %.6f got %.6f)",
                                    length(bad), n_sample, want[bad[1]], got[bad[1]]))

  list(problems = problems, n_obs = n_obs, n_vars = n_vars, obsm_keys = obsm_keys,
       hvg_n = hvg_h5, n_sampled = n_sample, n_sampled_nonzero = sum(want > 0),
       x_dtype = as.character(py_to_r(bi$str(a$X$dtype))),
       x_class = as.character(py_to_r(bi$str(bi$type(a$X)))))
}

run_worker <- function(key) {
  trim <- file.path(TRIM_DIR, paste0(key, ".rds"))
  if (!file.exists(trim)) stop("No trimmed object for ", key, " — run stage 2 first.")
  suppressPackageStartupMessages({ library(Seurat); library(SeuratObject) })
  log_msg("loading trimmed object")
  obj <- readRDS(trim)

  # Seurat v5 layered assays must be joined before export.
  if (inherits(obj[["RNA"]], "Assay5")) {
    lyrs <- SeuratObject::Layers(obj[["RNA"]])
    if (sum(grepl("^data", lyrs)) > 1) { log_msg("JoinLayers on RNA (", length(lyrs), " layers)"); obj <- JoinLayers(obj) }
  }

  dir.create(H5AD_DIR, showWarnings = FALSE, recursive = TRUE)
  dir.create(CHECK_DIR, showWarnings = FALSE, recursive = TRUE)
  path <- h5ad_out(key); tmp <- paste0(path, ".partial")
  if (file.exists(tmp)) unlink(tmp)

  requested <- if (!is.null(opts$writer) && !isTRUE(opts$writer)) as.character(opts$writer) else NULL
  chain <- if (!is.null(requested)) requested else c("anndataR", "sceasy", "direct")
  writers <- list(anndataR = write_anndataR, sceasy = write_sceasy, direct = write_direct)

  used <- NA_character_; errs <- list(); v <- NULL
  for (w in chain) {
    ok <- tryCatch({ log_msg("writer: ", w); writers[[w]](obj, tmp); TRUE },
                   error = function(e) { log_msg("  writer ", w, " failed: ", conditionMessage(e))
                                         errs[[w]] <<- conditionMessage(e); FALSE })
    if (!ok || !file.exists(tmp)) { if (file.exists(tmp)) unlink(tmp); next }

    log_msg("  verifying round trip")
    v <- verify_h5ad(obj, tmp)
    if (!length(v$problems)) { used <- w; break }
    # A file that does not round-trip is worse than no file: report and move on.
    log_msg("  writer ", w, " produced a file that failed verification:")
    for (p in v$problems) log_msg("    - ", p)
    errs[[w]] <- paste(v$problems, collapse = "; ")
    unlink(tmp); v <- NULL
  }
  if (is.na(used)) stop("no writer produced a verified h5ad: ",
                        paste(names(errs), unlist(errs), sep = ": ", collapse = " | "))

  v$writer <- used; v$writer_errors <- errs; v$key <- key
  v$file_mb <- round(file.info(tmp)$size / 1024^2, 1)
  write_json_atomic(v, file.path(CHECK_DIR, paste0(key, "_h5ad.json")))
  file.rename(tmp, path)
  log_msg(sprintf("ok: %d obs x %d vars, obsm [%s], hvg %d, %.0f MB (%d/%d sampled values non-zero)",
                  v$n_obs, v$n_vars, paste(v$obsm_keys, collapse = ", "), v$hvg_n,
                  v$file_mb, v$n_sampled_nonzero, v$n_sampled))
  invisible(TRUE)
}

if (flag(opts, "worker")) {
  key <- as.character(opts$dataset)
  run_worker_guarded(STAGE, key, function() run_worker(key))
} else {
  ensure_dirs(); dir.create(H5AD_DIR, showWarnings = FALSE, recursive = TRUE)
  cfg <- load_config(); keys <- select_datasets(cfg, opts)
  log_msg("datasets: ", paste(keys, collapse = ", "))
  run_stage_driver(STAGE, file.path(script_dir(), "03_to_h5ad.R"), keys, h5ad_out, opts)
}
