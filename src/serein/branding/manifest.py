"""Canonical registry of Serein branding assets (S7.2 Section 9).

Documents every branding asset this repository ships or expects to
ship - purpose, format, whether it is a source-of-truth or a generated
derivative, dimensions, licensing/provenance, and intended contexts.
Nothing here writes any file; this is the same kind of declarative
inventory ``desktop.config.RESOURCES`` already provides for desktop
config files.

Per the S7.2 asset-handoff contract (Section 5): an asset whose
``status`` is ``"pending_asset_request"`` has no approved final file
yet - its ``repo_path`` names where it will live once provided, not a
file that currently exists. :func:`missing_assets` only ever flags an
asset whose status claims the file should already exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_REPO_ROOT = Path(__file__).resolve().parents[3]

AssetCategory = Literal["logo", "wallpaper", "boot", "terminal", "icons", "tokens"]
AssetStatus = Literal["shipped", "pending_asset_request"]
AssetKind = Literal["source", "derivative", "documentation"]


@dataclass(frozen=True)
class BrandingAsset:
    id: str
    category: AssetCategory
    kind: AssetKind
    repo_path: str
    purpose: str
    format: str
    dimensions: str | None
    derived_from: str | None
    contexts: tuple[str, ...]
    license: str
    provenance: str
    status: AssetStatus


ASSETS: tuple[BrandingAsset, ...] = (
    BrandingAsset(
        id="design-tokens",
        category="tokens",
        kind="source",
        repo_path="branding/tokens/design-tokens.json",
        purpose=(
            "Canonical color/motion/visual-ratio values for the Quiet Velocity "
            "design language."
        ),
        format="JSON",
        dimensions=None,
        derived_from=None,
        contexts=("build-tooling", "docs", "future theme generation"),
        license="Serein-OS project (see repository LICENSE)",
        provenance="Authored directly for S7.2 Section 6.",
        status="shipped",
    ),
    BrandingAsset(
        id="terminal-mark-ascii",
        category="terminal",
        kind="derivative",
        repo_path="branding/terminal/serein-mark.txt",
        purpose=(
            "Mandatory ASCII/Unicode fallback mark for Fastfetch and any "
            "terminal without image support (S7.2 Section 12)."
        ),
        format="text/plain (UTF-8)",
        dimensions="<=80 columns",
        derived_from="serein-logo-primary",
        contexts=("tty", "ssh", "minimal terminal", "fastfetch"),
        license="Serein-OS project (see repository LICENSE)",
        provenance=(
            "Hand-derived approximation of the polygonal droplet/S mark - "
            "not a substitute for the approved logo once available."
        ),
        status="shipped",
    ),
    BrandingAsset(
        id="serein-logo-primary",
        category="logo",
        kind="source",
        repo_path="branding/logo/serein-logo-primary.svg",
        purpose=(
            "Master vector logo (polygonal water droplet with S negative-space, "
            "~7-9 facets) - the single source of truth every other logo variant "
            "derives from."
        ),
        format="SVG",
        dimensions=None,
        derived_from=None,
        contexts=("primary branding", "docs", "derivative generation"),
        license="TBD - set when the approved asset is provided",
        provenance=(
            "Requested from the project's visual-asset provider "
            "(S7.2 Section 5) - not yet provided."
        ),
        status="pending_asset_request",
    ),
    BrandingAsset(
        id="serein-logo-monochrome",
        category="logo",
        kind="derivative",
        repo_path="branding/logo/serein-logo-monochrome.svg",
        purpose=(
            "Flat single-color mark for contexts needing one currentColor fill "
            "(favicon fallback, GRUB, small icon composition)."
        ),
        format="SVG",
        dimensions=None,
        derived_from="serein-logo-primary",
        contexts=("favicon", "grub", "small icon"),
        license="TBD - set when the approved asset is provided",
        provenance=(
            "Deterministic single-color derivative of serein-logo-primary "
            "(recolor facets to currentColor) - generated once the primary "
            "source exists, never hand-invented separately."
        ),
        status="pending_asset_request",
    ),
    BrandingAsset(
        id="serein-plymouth-mark",
        category="boot",
        kind="derivative",
        repo_path="branding/boot/serein-plymouth-mark.png",
        purpose="Centered droplet mark for the Plymouth boot splash (S7.2 Section 17).",
        format="PNG",
        dimensions="TBD - derive from theme resolution once the Plymouth theme is built",
        derived_from="serein-logo-primary",
        contexts=("plymouth", "boot"),
        license="TBD - set when the approved asset is provided",
        provenance=(
            "Raster derivative of serein-logo-primary - generated once the "
            "primary source exists."
        ),
        status="pending_asset_request",
    ),
    BrandingAsset(
        id="serein-grub-mark",
        category="boot",
        kind="derivative",
        repo_path="branding/boot/serein-grub-mark.png",
        purpose=(
            "Small wordmark/logo for the GRUB menu background (S7.2 Section 16) - "
            "branding only, never altering GRUB functionality."
        ),
        format="PNG",
        dimensions="TBD - derive from GRUB theme resolution",
        derived_from="serein-logo-primary",
        contexts=("grub",),
        license="TBD - set when the approved asset is provided",
        provenance=(
            "Raster derivative of serein-logo-primary - generated once the "
            "primary source exists."
        ),
        status="pending_asset_request",
    ),
    BrandingAsset(
        id="serein-app-icon",
        category="icons",
        kind="derivative",
        repo_path="branding/icons/serein-app-icon.svg",
        purpose="Application/favicon-style icon usable at very small sizes.",
        format="SVG",
        dimensions=None,
        derived_from="serein-logo-primary",
        contexts=("app icon", "favicon"),
        license="TBD - set when the approved asset is provided",
        provenance=(
            "Deterministic derivative of serein-logo-primary - generated once "
            "the primary source exists."
        ),
        status="pending_asset_request",
    ),
    BrandingAsset(
        id="serein-wallpaper-default-dark",
        category="wallpaper",
        kind="source",
        repo_path="branding/wallpaper/serein-wallpaper-default-dark.png",
        purpose=(
            "Default desktop wallpaper - dark navy, subtle mist/rain atmosphere, "
            "understated polygon mark (S7.2 Section 14)."
        ),
        format="PNG or WebP",
        dimensions="3840x2160 (crop/scale-safe for 2560x1440 and 1920x1080 derivatives)",
        derived_from=None,
        # Also serves as the SDDM login background (Section 18/23 of the
        # Phase-7-completion brief) - deliberately the SAME file, never a
        # second near-identical hero-image asset request (Section 13's
        # "prefer one source, never duplicate" principle applied to a
        # raster asset, not just the vector logo).
        contexts=("desktop wallpaper", "sddm background"),
        license="TBD - set when the approved asset is provided",
        provenance=(
            "Requested from the project's visual-asset provider (S7.2 Section 5) - "
            "not yet provided; cannot be derived from the vector logo alone "
            "(real illustration/atmosphere work)."
        ),
        status="pending_asset_request",
    ),
)


def missing_assets(root: Path | None = None) -> list[BrandingAsset]:
    """Assets whose status claims ``"shipped"`` but whose ``repo_path``
    file does not actually exist - a packaging defect, never a host
    state (mirrors ``desktop.config.missing_resources``). An asset
    still ``"pending_asset_request"`` is never flagged here - its file
    is not expected to exist yet."""
    base = root if root is not None else _REPO_ROOT
    return [a for a in ASSETS if a.status == "shipped" and not (base / a.repo_path).is_file()]


def pending_asset_requests() -> list[BrandingAsset]:
    return [a for a in ASSETS if a.status == "pending_asset_request"]
