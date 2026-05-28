# Dataset Fixtures

This directory contains lightweight metadata and mapping examples that are safe to keep in Git.

Large 3D model files, archives, spreadsheets, and screen recordings are intentionally excluded from normal Git history. Store those assets as release artifacts, external demo datasets, or Git LFS objects if the project owner decides to publish them.

The small root-level fixtures `test_model.glb`, `test_image.jpg`, and `MSF.xlsx` are synthetic generated files kept because WebHDP setup/admin smoke tests use them directly.
