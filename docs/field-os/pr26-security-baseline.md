# PR26 dependency review gate

## Blocking dependency finding (2026-09-22)

The installed-runtime audit reports `pdfkit==1.0.0`, pulled by Frappe's `pdfkit~=1.0.0` requirement, for CVE-2025-26240 / GHSA-9g3x-6x24-vf9f. The audit currently emits the same advisory twice. The [GitHub reviewed advisory](https://github.com/advisories/GHSA-9g3x-6x24-vf9f) lists affected versions through 1.0.0 and no patched release. Local dependency resolution reproduced the CI finding.

The inspected Frappe `frappe/utils/pdf.py` path explicitly disables JavaScript and local file access before calling `pdfkit.from_string`. This is relevant mitigation evidence, not proof that every call path is safe or an approved exception. The audit gate remains blocking, with no ignored vulnerability IDs. Resolve through a reviewed upstream renderer replacement/fix or a security-owner-approved, documented, time-limited exception after reviewing all renderer entrypoints. Do not uninstall the dependency or override Frappe's constraints just to make CI green. PR26 and its dependent release chain cannot land while this gate remains unresolved.
