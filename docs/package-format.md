# Package format and validation

The authoritative contract for application teams is `APPLICATION_RELEASE_CONTRACT.md`; this
page documents how SCARLET validates and stores packages.

## Validation pipeline (`app/deployment/validator.py`)

1. **Extension**: `.scarlet.tar.gz` (also `.tar.gz`, `.tgz`).
2. **Magic bytes**: gzip header; tar integrity while iterating.
3. **Members** (without extracting): reject absolute paths, `..`, drive letters, unsafe
   characters; reject symlinks, hard links, devices, FIFOs, setuid/setgid modes; enforce
   `SCARLET_MAX_PACKAGE_MEMBERS` (20 000) and `SCARLET_MAX_PACKAGE_UNCOMPRESSED_MB` (8192);
   warn on unknown top-level entries.
4. **Manifest**: `manifest.yaml` at the root, ≤ 256 KiB, UTF-8, YAML mapping, strict Pydantic
   schema (`app/deployment/manifest.py`, `manifest_version: 1`).
5. **Application**: `application` must exist in SCARLET and be enabled; the manifest runtime must
   be allowed for the application; hooks require `allow_hooks`.
6. **Version**: SemVer; not previously released for the application; identical checksum already
   released → duplicate error.
7. **Runtime compatibility**: image xor compose for docker/podman; kubernetes section for kubernetes.
8. **Required files/directories**: `image.archive`, `environment_files`, hook scripts, compose file,
   `kubernetes.manifests`, helm chart/values must exist in the archive.
9. **SHA-256**: computed while streaming the upload and again on the stored file; stored on the
   `Package` and copied to the immutable `ApplicationVersion`.
10. **Duplicate detection**: same checksum released before → error.
11. **Malware scan (optional)**: `SCARLET_MALWARE_SCANNER_COMMAND="clamscan --no-summary {path}"`;
    non-zero exit → `QUARANTINED`.

Result: `VALID` (release created when `auto_release` is on) or `INVALID` with the full error list;
warnings are informational. INVALID packages can be re-validated or deleted; released packages are
immutable.

## Storage (`app/deployment/storage.py`)

`LocalFilesystemArtifactStorage` under `SCARLET_ARTIFACT_PATH` (outside the web root):

```
<root>/_incoming/<random>.tar.gz              upload until validated (purged after 24 h)
<root>/<application_id>/<version>/package.tar.gz   immutable release (chmod 0440)
<root>/<application_id>/<version>/manifest.yaml
<root>/<application_id>/<version>/metadata.json
```

Only metadata (checksum, size, manifest JSON) lives in PostgreSQL. The interface allows S3/MinIO
implementations (`store_incoming`, `promote`, `open`, `local_path`, `delete`, `checksum`, …).

## Integrity checks after release

- Deployment step *Validate package* re-hashes the artifact and compares with the version checksum.
- Pre-flight *Package integrity* does the same.
- Applications → version → manifest dialog shows *artifact checksum verified*; a mismatch raises a
  CRITICAL `ARTIFACT_CHECKSUM_MISMATCH` security event.
- The remote copy is verified with `sha256sum` before extraction.

## Building packages

`scripts/build-scarlet-package.py --source DIR --version X.Y.Z --output dist/` (library:
`app/deployment/packager.py`): normalises member names, strips symlinks, sets 0644/0755 modes,
writes `checksums.sha256`, validates the result and writes `<name>.sha256`.
`flask scarlet validate-package FILE` validates an existing archive without uploading.
