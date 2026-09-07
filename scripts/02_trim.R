#!/usr/bin/env Rscript
# Stage 2 — trim.
#
# Produces a minimal Seurat object per dataset: RNA `data` layer only, plottable
# metadata only, embedding reductions only, plus a highly-variable-gene list
# stashed in misc$hvg for the h5ad writer to put into var/highly_variable.
#
#   Rscript scripts/02_trim.R [--dataset KEY] [--force] [--dry-run] [--include-duplicates]

suppressWarnings(suppressPackageStartupMessages(
  source(file.path(dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1])), "00_common.R"))
))
suppressPackageStartupMessages({ library(Seurat); library(SeuratObject); library(Matrix) })

opts     <- parse_args()
STAGE    <- "02_trim"
TRIM_DIR <- file.path(BUILD_DIR, "trimmed")
trim_out <- function(k) file.path(TRIM_DIR, paste0(k, ".rds"))

# Pull per-cell spatial coordinates out of @images and return them as a matrix
# ordered like colnames(obj), or NULL when the object has none / is incomplete.
#
# Images are consumed in order, each contributing only the cells not already
# covered, so overlapping subset-images (VisiumHD ships both whole-slide and
# per-sample FOVs of the same spots) do not duplicate cells. If the chosen
# images occupy overlapping coordinate ranges they are laid out on a grid --
# without that, five TMA slides all starting near the origin would be stacked on
# top of each other. Ranges that are already disjoint (CosMx global slide
# coordinates) are left exactly as they are.
extract_spatial <- function(obj, group_col = NULL) {
  ims <- names(obj@images)
  if (!length(ims)) return(NULL)
  cells <- colnames(obj)
  taken <- character(0)
  parts <- list()
  for (nm in ims) {
    co <- tryCatch(SeuratObject::GetTissueCoordinates(obj, image = nm), error = function(e) NULL)
    if (is.null(co) || !all(c("x", "y") %in% colnames(co))) next
    rn <- if ("cell" %in% colnames(co)) as.character(co$cell) else rownames(co)
    keep <- !(rn %in% taken) & (rn %in% cells) & !is.na(co$x) & !is.na(co$y)
    if (!any(keep)) next
    parts[[nm]] <- data.frame(cell = rn[keep], x = as.numeric(co$x)[keep],
                              y = as.numeric(co$y)[keep], stringsAsFactors = FALSE)
    taken <- c(taken, rn[keep])
  }
  if (!length(parts)) return(NULL)
  log_msg("spatial: ", length(parts), " image(s) contribute coordinates for ",
          length(taken), "/", length(cells), " cells")
  if (length(taken) < length(cells)) {
    log_msg("spatial: SKIPPED - ", length(cells) - length(taken),
            " cells have no coordinates, a partial embedding would be misleading")
    return(NULL)
  }

  d <- do.call(rbind, parts)
  # Tiles are what gets laid out. By default each source image is a tile; with
  # `spatial_group` set, all images of one sample form a single tile, so true
  # within-sample geometry is preserved while the empty space between samples
  # on the slide is removed.
  force_grid <- FALSE
  if (!is.null(group_col) && group_col %in% colnames(obj@meta.data)) {
    g <- as.character(obj@meta.data[[group_col]])[match(d$cell, cells)]
    g[is.na(g)] <- "unassigned"
    parts <- split(d, g)
    force_grid <- TRUE
    log_msg("spatial: grouping ", length(parts), " tile(s) by ", group_col)
  } else {
    parts <- lapply(parts, identity)
  }

  boxes <- lapply(parts, function(p) c(min(p$x), max(p$x), min(p$y), max(p$y)))
  overlap <- force_grid
  if (!overlap && length(boxes) > 1) {
    for (i in seq_len(length(boxes) - 1)) {
      for (j in (i + 1):length(boxes)) {
        a <- boxes[[i]]; b <- boxes[[j]]
        if (a[1] <= b[2] && b[1] <= a[2] && a[3] <= b[4] && b[3] <= a[4]) { overlap <- TRUE; break }
      }
      if (overlap) break
    }
  }
  if (overlap) {
    n <- length(parts)
    ncols <- ceiling(sqrt(n))
    span_x <- max(vapply(boxes, function(b) b[2] - b[1], 0)) * 1.06
    span_y <- max(vapply(boxes, function(b) b[4] - b[3], 0)) * 1.06
    log_msg("spatial: laying ", n, " tile(s) out on a ", ncols, "-column grid",
            if (force_grid) "" else " (extents overlap)")
    for (i in seq_along(parts)) {
      b <- boxes[[i]]
      col <- (i - 1) %% ncols
      row <- (i - 1) %/% ncols
      parts[[i]]$x <- parts[[i]]$x - b[1] + col * span_x
      parts[[i]]$y <- parts[[i]]$y - b[3] + row * span_y
    }
  } else {
    log_msg("spatial: tile extents are disjoint; keeping original coordinates")
  }

  d <- do.call(rbind, parts)
  d <- d[match(cells, d$cell), ]
  m <- cbind(spatial_1 = d$x, spatial_2 = -d$y)   # flip y: image origin is top-left
  rownames(m) <- cells
  m
}

NA_TOKENS <- c("NA", "NaN", "", " ", "unknown", "Unknown", "UNKNOWN", "N/A", "n/a", "NULL", "none", "None")

blank_to_na <- function(v) { v <- as.character(v); v[v %in% NA_TOKENS] <- NA_character_; v }

# Colour columns in these objects mix hex with R colour names ("tan2", "grey70").
is_colour_column <- function(v) {
  v <- unique(blank_to_na(v)); v <- v[!is.na(v)]
  length(v) > 0 && length(v) <= 256 &&
    all(vapply(v, function(x) !inherits(try(grDevices::col2rgb(x), silent = TRUE), "try-error"), logical(1)))
}

as_hex <- function(x) {
  m <- grDevices::col2rgb(x)
  grDevices::rgb(m[1, ], m[2, ], m[3, ], maxColorValue = 255)
}

# Decide what happens to every metadata column, and why. Returns the curated
# data.frame plus a decision log and the extracted label -> colour maps.
curate_metadata <- function(md, cfg, dcfg) {
  max_card   <- cfg$max_categorical_cardinality %||% 100
  keep_extra <- unlist(dcfg$obs_keep_extra %||% list())
  drop_list  <- unlist(dcfg$obs_drop %||% list())
  coerce     <- unlist(dcfg$obs_numeric_coerce %||% list())
  min_parse  <- cfg$numeric_coerce_min_parsed %||% 0.9

  decisions <- list(); colours <- list(); keep <- character(0)
  nm_all <- colnames(md)
  card_of <- function(nm) length(unique(stats::na.omit(blank_to_na(md[[nm]]))))

  # 1. colour palettes: pair `<prefix>_color` with the label column that has the
  #    same number of levels, and lift the mapping out of obs entirely
  #    (Vitessce takes set colours from the config, not from a cell column).
  for (nm in grep("_colou?r$", nm_all, value = TRUE)) {
    if (!is_colour_column(md[[nm]])) next
    prefix <- sub("_colou?r$", "", nm)
    n_col <- card_of(nm)
    cands <- setdiff(grep(paste0("^", prefix), nm_all, value = TRUE), nm)
    cands <- cands[!grepl("_colou?r$", cands)]
    # A valid partner is one the colour is a *function* of: the number of
    # distinct (label, colour) pairs must equal the number of distinct colours.
    # Cardinality alone is not enough — two columns can share a level count and
    # still cross-cut each other.
    col_v <- blank_to_na(md[[nm]])
    ok <- cands[vapply(cands, function(x) {
      lv <- blank_to_na(md[[x]])
      pairs <- unique(data.frame(l = lv, c = col_v, stringsAsFactors = FALSE))
      pairs <- pairs[!is.na(pairs$l) & !is.na(pairs$c), ]
      nrow(pairs) == n_col && length(unique(pairs$l)) == n_col
    }, logical(1))]
    # Prefer a human-readable label column over id codes.
    rank_of <- function(x) if (grepl("_label_final$", x)) 1L else if (grepl("_label$", x)) 2L else
                           if (grepl("_(id|id_label)$", x)) 4L else 3L
    partner <- if (length(ok)) ok[order(vapply(ok, rank_of, 1L), nchar(ok))][1] else NA_character_
    if (!is.na(partner)) {
      lab <- blank_to_na(md[[partner]]); col <- blank_to_na(md[[nm]])
      tab <- unique(data.frame(label = lab, colour = col, stringsAsFactors = FALSE))
      tab <- tab[!is.na(tab$label) & !is.na(tab$colour), ]
      tab <- tab[!duplicated(tab$label), ]
      colours[[partner]] <- as.list(stats::setNames(as_hex(tab$colour), tab$label))
      decisions[[nm]] <- list(action = "drop",
                              reason = sprintf("colour palette for %s (%d entries); lifted to config colours",
                                               partner, nrow(tab)))
    } else {
      decisions[[nm]] <- list(action = "drop",
                              reason = sprintf("colour palette (%d colours), no label column of matching cardinality", n_col))
    }
  }

  for (nm in nm_all) {
    if (!is.null(decisions[[nm]])) next
    v <- md[[nm]]
    coerce_note <- NULL

    if (nm %in% drop_list) { decisions[[nm]] <- list(action = "drop", reason = "config obs_drop"); next }
    if (is.list(v) && !is.factor(v)) { decisions[[nm]] <- list(action = "drop", reason = "list column"); next }

    # 2. character columns that are really numeric (PMI, RIN ...). Literal "NA"
    #    and friends count as missing, not as unparseable.
    if (nm %in% coerce && !is.numeric(v)) {
      chr <- blank_to_na(v)
      num <- suppressWarnings(as.numeric(chr))
      unparsed <- unique(chr[is.na(num) & !is.na(chr)])
      frac <- if (length(chr)) mean(!is.na(num) | is.na(chr)) else 0
      if (frac >= min_parse) {
        n_lost <- sum(is.na(num) & !is.na(chr))
        if (n_lost > 0 && length(unique(chr[!is.na(chr)])) <= max_card) {
          # Coercion would erase real values (e.g. fetal ages "pcw_14"), so keep
          # the verbatim column alongside the numeric one.
          orig <- paste0(nm, "_original")
          md[[orig]] <- factor(chr); keep <- c(keep, orig)
          decisions[[orig]] <- list(action = "keep", type = "categorical",
                                    reason = sprintf("verbatim %s preserved: %d cells are not numeric (%s)",
                                                     nm, n_lost, paste(utils::head(unparsed, 5), collapse = ", ")))
          log_msg("  NOTE ", nm, ": ", n_lost, " cells not numeric (",
                  paste(utils::head(unparsed, 5), collapse = ", "), ") -> kept verbatim as ", orig)
        }
        md[[nm]] <- num; keep <- c(keep, nm)
        decisions[[nm]] <- list(action = "keep", type = "numeric",
                                reason = sprintf("coerced from character (%.1f%% parsed, %d cells set to NA)",
                                                 100 * frac, n_lost))
        next
      }
      # Refuse to coerce: turning the unparseable values into NA would silently
      # delete real samples (e.g. fetal ages recorded as "pcw_14").
      coerce_note <- sprintf("numeric coercion refused: only %.1f%% parsed; unparseable e.g. %s",
                             100 * frac, paste(utils::head(unparsed, 5), collapse = ", "))
      log_msg("  NOTE ", nm, ": ", coerce_note)
    }

    if (is.numeric(md[[nm]])) {
      if (all(is.na(md[[nm]]))) { decisions[[nm]] <- list(action = "drop", reason = "all NA"); next }
      keep <- c(keep, nm)
      decisions[[nm]] <- list(action = "keep", type = "numeric", reason = "numeric / QC")
      next
    }

    v <- blank_to_na(v)
    card <- length(unique(v[!is.na(v)]))
    if (card < 2) { decisions[[nm]] <- list(action = "drop", reason = sprintf("cardinality %d", card)); next }

    # 3. `X_id` / `X_id_label` restate `X_label`; keep one representation.
    base <- sub("_(id|id_label)$", "", nm)
    if (nm != base && any(c(paste0(base, "_label"), paste0(base, "_label_final")) %in% nm_all)) {
      decisions[[nm]] <- list(action = "drop", reason = paste0("redundant with ", base, "_label"))
      next
    }

    if (card > max_card && !(nm %in% keep_extra)) {
      decisions[[nm]] <- list(action = "drop", reason = sprintf("cardinality %d > %d", card, max_card))
      next
    }
    md[[nm]] <- factor(v)
    keep <- c(keep, nm)
    decisions[[nm]] <- list(action = "keep", type = "categorical",
                            reason = sprintf("cardinality %d", card),
                            over_cutoff = card > max_card, note = coerce_note)
  }

  for (nm in names(colours)) {
    if (!(nm %in% keep)) {
      log_msg("  NOTE colour map for ", nm, " discarded: that column was not kept")
      colours[[nm]] <- NULL
    }
  }
  list(md = md[, keep, drop = FALSE], decisions = decisions, colours = colours, kept = keep)
}

run_worker <- function(key) {
  cfg  <- load_config()
  dcfg <- cfg$datasets[[key]] %||% list()
  m    <- read_json_if_exists(MANIFEST)
  ds   <- m$datasets[[key]]
  if (is.null(ds)) stop("Dataset not in manifest: ", key)

  log_msg("loading ", ds$rel_path)
  obj <- read_object(ds$path)
  size_before <- as.numeric(utils::object.size(obj))
  n_assays_before <- length(Assays(obj)); n_red_before <- length(Reductions(obj))

  # --- spatial coordinates (before @images is discarded) --------------------
  spatial <- if (isFALSE(dcfg$spatial)) NULL else
    extract_spatial(obj, dcfg$spatial_group %||% NULL)

  # --- assays: one assay, data layer only -----------------------------------
  # The source assay is whatever the object calls it (CosMx panels live in
  # "Nanostring"); downstream stages only ever see "RNA".
  keep_assay <- dcfg$assay %||% DefaultAssay(obj)
  if (!(keep_assay %in% Assays(obj))) stop("Assay not present: ", keep_assay)
  DefaultAssay(obj) <- keep_assay
  for (a in setdiff(Assays(obj), keep_assay)) obj[[a]] <- NULL

  # Seurat v5 layered assays must be joined before a single data matrix exists.
  if (inherits(obj[[keep_assay]], "Assay5")) {
    lyrs <- SeuratObject::Layers(obj[[keep_assay]])
    if (sum(grepl("^data", lyrs)) > 1 || sum(grepl("^counts", lyrs)) > 1) {
      log_msg("JoinLayers on ", keep_assay, " (", paste(lyrs, collapse = ", "), ")")
      obj <- JoinLayers(obj, assay = keep_assay)
    }
  }

  rna <- obj[[keep_assay]]
  has_data <- tryCatch(prod(dim(LayerData(rna, layer = "data"))) > 0, error = function(e) FALSE)
  if (!has_data) {
    log_msg("WARNING: no `data` layer; normalising counts in place")
    obj <- NormalizeData(obj, verbose = FALSE)
    rna <- obj[[keep_assay]]
  }
  data_mat <- LayerData(rna, layer = "data")
  # Rebuild as a plain v3 Assay holding only `data`: it is what the h5ad writer
  # expects and it drops scale.data/counts without slot surgery.
  new_assay <- SeuratObject::CreateAssayObject(data = data_mat)
  SeuratObject::VariableFeatures(new_assay) <- intersect(
    tryCatch(VariableFeatures(obj, assay = keep_assay), error = function(e) character(0)),
    rownames(new_assay))
  obj[["RNA_trimmed"]] <- new_assay
  DefaultAssay(obj) <- "RNA_trimmed"
  for (a in setdiff(Assays(obj), "RNA_trimmed")) obj[[a]] <- NULL
  obj <- RenameAssays(obj, assay.name = "RNA_trimmed", new.assay.name = "RNA", verbose = FALSE)
  DefaultAssay(obj) <- "RNA"
  if (!identical(keep_assay, "RNA")) log_msg("assay ", keep_assay, " -> RNA")

  # --- reductions: 2-D embeddings only --------------------------------------
  if (!is.null(spatial)) {
    obj[["spatial"]] <- SeuratObject::CreateDimReducObject(
      embeddings = spatial, key = "spatial_", assay = "RNA")
  }
  pat <- dcfg$embedding_pattern %||% cfg$embedding_pattern %||% "^(umap|tsne|spatial)"
  is_plottable <- vapply(Reductions(obj), function(r) {
    grepl(pat, r, ignore.case = TRUE) ||
      isTRUE(ncol(Embeddings(obj, reduction = r)) == 2)   # e.g. integrated.rpca
  }, logical(1))
  drop_red <- Reductions(obj)[!is_plottable]
  for (r in drop_red) obj[[r]] <- NULL
  if (!length(Reductions(obj))) stop("No 2-D embedding to plot in this object")
  log_msg("reductions kept: ", paste(Reductions(obj), collapse = ", "),
          " | dropped: ", paste(drop_red, collapse = ", "))

  obj@graphs <- list(); obj@commands <- list(); obj@images <- list()
  if (.hasSlot(obj, "neighbors")) obj@neighbors <- list()

  # --- metadata -------------------------------------------------------------
  cur <- curate_metadata(obj@meta.data, cfg, dcfg)
  n_before <- ncol(obj@meta.data)
  obj@meta.data <- cur$md
  log_msg(sprintf("metadata: %d -> %d columns", n_before, ncol(cur$md)))
  for (nm in names(cur$decisions)) {
    d <- cur$decisions[[nm]]
    if (identical(d$action, "drop")) log_msg("  drop ", nm, " (", d$reason, ")")
  }

  # --- highly variable genes ------------------------------------------------
  target <- cfg$hvg_target %||% 4000
  hvg <- tryCatch(VariableFeatures(obj), error = function(e) character(0))
  if (length(hvg) >= target) {
    hvg <- utils::head(hvg, target)
    log_msg("HVG: using top ", length(hvg), " of the object's existing variable features")
  } else {
    log_msg("HVG: computing ", target, " variable features (object had ", length(hvg), ")")
    obj <- FindVariableFeatures(obj, nfeatures = target, verbose = FALSE)
    hvg <- utils::head(VariableFeatures(obj), target)
  }
  hvg <- intersect(hvg, rownames(obj))
  obj@misc <- list(hvg = hvg, colours = cur$colours,
                   dataset_key = key, title = dcfg$title %||% key)
  VariableFeatures(obj) <- hvg

  gc(full = TRUE)
  size_after <- as.numeric(utils::object.size(obj))
  dir.create(TRIM_DIR, showWarnings = FALSE, recursive = TRUE)
  saveRDS(obj, trim_out(key), compress = FALSE)   # speed over disk: build artefact

  report <- list(
    key = key,
    cells = ncol(obj), features = nrow(obj),
    assays_before = n_assays_before, assays_after = length(Assays(obj)),
    reductions_before = n_red_before, reductions_after = length(Reductions(obj)),
    reductions_kept = Reductions(obj), reductions_dropped = drop_red,
    obs_before = n_before, obs_after = ncol(cur$md), obs_kept = cur$kept,
    obs_decisions = cur$decisions, colour_maps = cur$colours,
    hvg_n = length(hvg),
    size_mb_before = round(size_before / 1024^2, 1),
    size_mb_after  = round(size_after / 1024^2, 1),
    file_mb = round(file.info(trim_out(key))$size / 1024^2, 1)
  )
  write_json_atomic(report, file.path(TRIM_DIR, paste0(key, "_report.json")))
  log_msg(sprintf("size %.0f MB -> %.0f MB in memory; %.0f MB on disk",
                  report$size_mb_before, report$size_mb_after, report$file_mb))
  invisible(TRUE)
}

if (flag(opts, "worker")) {
  key <- as.character(opts$dataset)
  run_worker_guarded(STAGE, key, function() run_worker(key))
} else {
  ensure_dirs(); dir.create(TRIM_DIR, showWarnings = FALSE, recursive = TRUE)
  cfg  <- load_config()
  keys <- select_datasets(cfg, opts)
  log_msg("datasets: ", paste(keys, collapse = ", "))
  st <- run_stage_driver(STAGE, file.path(script_dir(), "02_trim.R"), keys, trim_out, opts)
  for (k in names(st)) {
    p <- file.path(TRIM_DIR, paste0(k, "_report.json"))
    if (!file.exists(p)) next
    r <- read_json_if_exists(p)
    log_msg(sprintf("%s: %s MB -> %s MB, obs %s -> %s, hvg %s",
                    k, r$size_mb_before, r$size_mb_after, r$obs_before, r$obs_after, r$hvg_n))
  }
}
