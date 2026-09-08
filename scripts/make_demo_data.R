#!/usr/bin/env Rscript
# Generates a small synthetic Seurat object so the pipeline can be exercised
# end to end without access to any real dataset. Structure mirrors the real
# inputs: an RNA assay with a normalised `data` layer, a UMAP, categorical and
# numeric metadata, and a palette column of the kind stage 2 lifts out.
#
#   Rscript scripts/make_demo_data.R <output.rds> [n_cells] [n_genes]

suppressPackageStartupMessages({ library(Seurat); library(SeuratObject); library(Matrix) })

args    <- commandArgs(trailingOnly = TRUE)
out     <- if (length(args) >= 1) args[[1]] else "demo.rds"
n_cells <- if (length(args) >= 2) as.integer(args[[2]]) else 600L
n_genes <- if (length(args) >= 3) as.integer(args[[3]]) else 400L

set.seed(1)
types    <- c("Microglia", "Monocyte", "T cell", "B cell")
palette  <- c(Microglia = "#9ACD32", Monocyte = "#D2B48C", `T cell` = "#00E5EE", `B cell` = "#A020F0")
label    <- sample(types, n_cells, replace = TRUE, prob = c(0.55, 0.2, 0.15, 0.1))

# Counts with a per-type marker block so expression is not uniform noise.
counts <- matrix(rpois(n_genes * n_cells, lambda = 0.3), nrow = n_genes)
markers <- split(seq_len(40), rep(seq_along(types), each = 10))
for (i in seq_along(types)) {
  rows <- markers[[i]]; cols <- which(label == types[i])
  counts[rows, cols] <- counts[rows, cols] + rpois(length(rows) * length(cols), lambda = 12)
}
rownames(counts) <- c("P2RY12", "CX3CR1", "TMEM119", "CSF1R", "AIF1", "ITGAM",
                      sprintf("GENE%04d", seq_len(n_genes - 6)))[seq_len(n_genes)]
colnames(counts) <- sprintf("cell_%05d", seq_len(n_cells))

obj <- CreateSeuratObject(counts = as(counts, "dgCMatrix"), project = "demo")
obj <- NormalizeData(obj, verbose = FALSE)
obj <- FindVariableFeatures(obj, nfeatures = min(200, n_genes), verbose = FALSE)

centres <- matrix(c(0, 0, 6, 1, 1, 6, 7, 7), ncol = 2, byrow = TRUE, dimnames = list(types, NULL))
emb <- centres[label, ] + matrix(rnorm(n_cells * 2, sd = 0.7), ncol = 2)
rownames(emb) <- colnames(obj); colnames(emb) <- c("umap_1", "umap_2")
obj[["umap"]] <- CreateDimReducObject(embeddings = emb, key = "umap_", assay = "RNA")

obj$Subclass_label <- label
obj$Subclass_color <- unname(palette[label])          # lifted out by stage 2
obj$condition      <- sample(c("control", "treated"), n_cells, replace = TRUE)
obj$donor          <- sample(sprintf("D%02d", 1:6), n_cells, replace = TRUE)
obj$Age            <- as.character(sample(c(20:80, "pcw_14"), n_cells, replace = TRUE))
obj$constant_col   <- "same"                          # dropped: cardinality 1
obj$percent.mt     <- runif(n_cells, 0, 8)

dir.create(dirname(out), showWarnings = FALSE, recursive = TRUE)
saveRDS(obj, out)
cat(sprintf("wrote %s: %d cells x %d genes\n", out, ncol(obj), nrow(obj)))
