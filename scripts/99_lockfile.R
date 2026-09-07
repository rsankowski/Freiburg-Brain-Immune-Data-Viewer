#!/usr/bin/env Rscript
# Writes renv.lock from the versions actually loaded by this pipeline.
# renv itself is not required (and is not installed into the user's library).
suppressWarnings(suppressPackageStartupMessages(
  source(file.path(dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1])), "00_common.R"))
))

pkgs <- c("Seurat", "SeuratObject", "Matrix", "jsonlite", "reticulate", "sceasy", "sp", "qs")
entries <- list()
for (p in pkgs) {
  if (!requireNamespace(p, quietly = TRUE)) next
  d <- utils::packageDescription(p)
  src <- if (!is.null(d$RemoteType)) d$RemoteType else if (!is.null(d$Repository)) "Repository" else "unknown"
  e <- list(Package = p, Version = as.character(utils::packageVersion(p)),
            Source = if (identical(src, "Repository")) "Repository" else src)
  if (identical(e$Source, "Repository")) e$Repository <- d$Repository %||% "CRAN"
  if (!is.null(d$RemoteUrl))  e$RemoteUrl <- d$RemoteUrl
  if (!is.null(d$RemoteRef))  e$RemoteRef <- d$RemoteRef
  if (!is.null(d$RemoteSha))  e$RemoteSha <- d$RemoteSha
  if (!is.null(d$RemoteRepo)) e$RemoteRepo <- d$RemoteRepo
  if (!is.null(d$RemoteUsername)) e$RemoteUsername <- d$RemoteUsername
  entries[[p]] <- e
}
lock <- list(
  R = list(Version = paste(R.version$major, R.version$minor, sep = "."),
           Repositories = list(list(Name = "CRAN", URL = "https://cloud.r-project.org"))),
  Packages = entries
)
write_json_atomic(lock, file.path(ROOT, "renv.lock"))
log_msg("wrote renv.lock with ", length(entries), " packages")
