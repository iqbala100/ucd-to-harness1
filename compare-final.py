#!/usr/bin/env python3
"""
Common YAMLs by (name + identifier) AND identical content, with per-category mappings.

Outputs:
  - <OUTPUT_BASE>\services\                (common across >=2 roots)
  - <OUTPUT_BASE>\services\all_roots\      (common across all roots)
  - <OUTPUT_BASE>\services\common_index.yaml  (detailed mapping)
  - <OUTPUT_BASE>\pipelines\               (common across >=2 roots)
  - <OUTPUT_BASE>\pipelines\all_roots\
  - <OUTPUT_BASE>\pipelines\common_index.yaml
  - <OUTPUT_BASE>\common_report.yaml       (summary)

Matching:
  1) Extract (name, identifier) per YAML (category-aware paths).
  2) Within each (name, identifier) group, files must have identical content
     (configurable comparison; default uses DeepHash with ignore_order=True).
"""

import os
import re
import shutil
import yaml
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
from collections import defaultdict
from deepdiff import DeepHash, DeepDiff

# ---------------- CONFIG ----------------

PIPELINES_DIRS = [
    r"C:\Users\hiiqb\Desktop\ucd-compare\ucd-to-harness1\harness_out_RG1\.harness\pipelines",
    r"C:\Users\hiiqb\Desktop\ucd-compare\ucd-to-harness1\harness_out_RG2\.harness\pipelines",
    r"C:\Users\hiiqb\Desktop\ucd-compare\ucd-to-harness1\harness_out_RG3\.harness\pipelines",
    r"C:\Users\hiiqb\Desktop\ucd-compare\ucd-to-harness1\harness_out_RG4\.harness\pipelines",
    r"C:\Users\hiiqb\Desktop\ucd-compare\ucd-to-harness1\harness_out_RG5\.harness\pipelines",
    r"C:\Users\hiiqb\Desktop\ucd-compare\ucd-to-harness1\harness_out_RG6\.harness\pipelines",
]

SERVICES_DIRS = [
    r"C:\Users\hiiqb\Desktop\ucd-compare\ucd-to-harness1\harness_out_RG1\.harness\services",
    r"C:\Users\hiiqb\Desktop\ucd-compare\ucd-to-harness1\harness_out_RG2\.harness\services",
    r"C:\Users\hiiqb\Desktop\ucd-compare\ucd-to-harness1\harness_out_RG3\.harness\services",
    r"C:\Users\hiiqb\Desktop\ucd-compare\ucd-to-harness1\harness_out_RG4\.harness\services",
    r"C:\Users\hiiqb\Desktop\ucd-compare\ucd-to-harness1\harness_out_RG5\.harness\services",
    r"C:\Users\hiiqb\Desktop\ucd-compare\ucd-to-harness1\harness_out_RG6\.harness\services",
]

OUTPUT_BASE = r"C:\Users\hiiqb\Desktop\ucd-compare\ucd-to-harness1\common_output"

CLEAN_DEST = False
CASE_INSENSITIVE_COMPARE = True
REQUIRE_BOTH_FIELDS = True

# Require identical content *after* metadata match:
REQUIRE_IDENTICAL_CONTENT = True

# How to compare content when REQUIRE_IDENTICAL_CONTENT is True:
#   "hash"     -> DeepHash(obj, ignore_order=IGNORE_ORDER_IN_CONTENT)
#   "deepdiff" -> DeepDiff(objA, objB, ignore_order=IGNORE_ORDER_IN_CONTENT) must be empty
CONTENT_COMPARE_MODE = "hash"
IGNORE_ORDER_IN_CONTENT = True  # lists and dict key order ignored

FIELD_PATHS = {
    "services": {
        "name":       ["service.name", "name", "metadata.name"],
        "identifier": ["service.identifier", "identifier", "metadata.identifier", "id"],
    },
    "pipelines": {
        "name":       ["pipeline.name", "name", "metadata.name"],
        "identifier": ["pipeline.identifier", "identifier", "metadata.identifier", "id"],
    },
    "_generic": {
        "name":       ["name", "metadata.name"],
        "identifier": ["identifier", "metadata.identifier", "id"],
    }
}

# ---------------- HELPERS ----------------

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def clean_folder(path: str):
    if not os.path.isdir(path):
        return
    for root, dirs, files in os.walk(path, topdown=False):
        for name in files:
            try: os.remove(os.path.join(root, name))
            except Exception: pass
        for name in dirs:
            try: os.rmdir(os.path.join(root, name))
            except Exception: pass

def sane_name(s: str) -> str:
    s = s.replace(os.sep, "__")
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)

def label_from_root(root: str) -> str:
    p = Path(root)
    try:
        return p.parent.name or "root"
    except Exception:
        return "root"

def list_yaml_files_recursively(root_dir: str) -> List[Tuple[str, str]]:
    out = []
    for r, _, files in os.walk(root_dir):
        for name in files:
            if name.lower().endswith((".yaml", ".yml")):
                ab = os.path.join(r, name)
                rel = os.path.relpath(ab, root_dir)
                out.append((ab, rel))
    return out

def load_first_yaml_doc(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        docs = list(yaml.safe_load_all(f))
        if not docs:
            return {}
        return docs[0] if docs[0] is not None else {}

def get_by_path(obj: Any, dotted: str) -> Optional[Any]:
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur

def find_first(obj: Any, paths: List[str]) -> Optional[Any]:
    for p in paths:
        v = get_by_path(obj, p)
        if v is not None:
            return v
    return None

def norm_str(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = str(v).strip()
    return v.lower() if CASE_INSENSITIVE_COMPARE else v

def extract_name_identifier(doc: Any, category: str) -> Tuple[Optional[str], Optional[str]]:
    fp = FIELD_PATHS.get(category, {})
    name_paths = fp.get("name", []) + FIELD_PATHS["_generic"]["name"]
    id_paths   = fp.get("identifier", []) + FIELD_PATHS["_generic"]["identifier"]
    name = norm_str(find_first(doc, name_paths))
    ident = norm_str(find_first(doc, id_paths))
    return name, ident

def deep_hash_signature(obj: Any) -> str:
    try:
        h = DeepHash(obj, ignore_order=IGNORE_ORDER_IN_CONTENT)
        return str(h[obj])
    except Exception:
        dumped = yaml.safe_dump(obj, sort_keys=True, allow_unicode=True)
        return hashlib.sha256(dumped.encode("utf-8")).hexdigest()

def content_equal(a: Any, b: Any) -> bool:
    if CONTENT_COMPARE_MODE == "hash":
        return deep_hash_signature(a) == deep_hash_signature(b)
    diff = DeepDiff(a, b, ignore_order=IGNORE_ORDER_IN_CONTENT)
    return not diff

def copy_with_label(abs_path: str, rel_from_root: str, root_label: str, out_dir: str):
    ensure_dir(out_dir)
    base_name = f"{root_label}__{sane_name(rel_from_root)}"
    if not base_name.lower().endswith((".yaml", ".yml")):
        base_name += ".yaml"
    dst = os.path.join(out_dir, base_name)
    ensure_dir(os.path.dirname(dst))
    shutil.copy2(abs_path, dst)
    return dst

# ---------------- CORE ----------------

def process_category(category: str, roots: List[str], out_base: str) -> Dict[str, Any]:
    """
    - Scan all roots for YAMLs in this category.
    - Extract (name, identifier).
    - Group by (name, identifier).
    - Within each group, split into content-equal clusters.
    - A cluster is 'common_any' if it spans >=2 roots; 'common_all' if it spans all roots.
    - Copy: one representative per root in each qualifying cluster.
    - Return stats + detailed groups for mapping files.
    """
    assert len(roots) >= 2, f"Need at least two input roots for {category}"

    out_dir_any = os.path.join(out_base, category)
    out_dir_all = os.path.join(out_dir_any, "all_roots")
    ensure_dir(out_dir_any); ensure_dir(out_dir_all)
    if CLEAN_DEST:
        clean_folder(out_dir_any)

    labels = [label_from_root(r) for r in roots]

    entries: List[Dict[str, Any]] = []
    skipped_missing_meta = 0

    # Scan and collect metadata + doc
    for idx, root in enumerate(roots):
        for ab, rel in list_yaml_files_recursively(root):
            try:
                doc = load_first_yaml_doc(ab) or {}
            except Exception:
                continue
            name, ident = extract_name_identifier(doc, category)
            if REQUIRE_BOTH_FIELDS and (not name or not ident):
                skipped_missing_meta += 1
                continue
            entries.append({
                "root_idx": idx,
                "root_label": labels[idx],
                "root": root,
                "abs": ab,
                "rel": rel,
                "name": name,
                "identifier": ident,
                "doc": doc,
            })

    # Group by (name, identifier)
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for e in entries:
        groups[(e["name"], e["identifier"])].append(e)

    root_count = len(roots)
    copied_any = copied_all = 0
    detailed_any: List[Dict[str, Any]] = []
    detailed_all: List[Dict[str, Any]] = []

    # Copy helpers
    def copy_cluster(cluster: List[Dict[str, Any]], base_dir: str) -> int:
        """Copy one representative per root in this cluster."""
        seen_roots = set()
        copied = 0
        for it in cluster:
            if it["root_idx"] in seen_roots:
                continue
            copy_with_label(it["abs"], it["rel"], it["root_label"], base_dir)
            seen_roots.add(it["root_idx"])
            copied += 1
        return copied

    # Build content clusters and mapping
    for (name, ident), items in groups.items():
        # Build clusters: by signature (hash) for IDs; deepdiff still allowed for equality check
        cluster_map: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for it in items:
            sig_for_id = deep_hash_signature(it["doc"])  # use as stable cluster_id
            cluster_map[sig_for_id].append(it)

        for cluster_id, cluster in cluster_map.items():
            # If strict content required, verify all in cluster are equal; otherwise skip verify
            roots_in_cluster = sorted({it["root_idx"] for it in cluster})
            if REQUIRE_IDENTICAL_CONTENT and CONTENT_COMPARE_MODE == "deepdiff":
                # Ensure all equal within cluster (pairwise)
                base_doc = cluster[0]["doc"]
                if any(not content_equal(base_doc, it["doc"]) for it in cluster[1:]):
                    continue  # skip inconsistent cluster

            # Decide common_any / common_all
            if len(roots_in_cluster) >= 2:
                # record details (exact files per root)
                files = [{
                    "root_label": it["root_label"],
                    "root_index": it["root_idx"],
                    "rel": it["rel"],
                    "abs": it["abs"]
                } for it in sorted(cluster, key=lambda x: (x["root_idx"], x["rel"]))]

                rec = {
                    "name": name,
                    "identifier": ident,
                    "cluster_id": cluster_id,
                    "roots_present": sorted(list({labels[i] for i in roots_in_cluster})),
                    "files": files
                }
                detailed_any.append(rec)
                copied_any += copy_cluster(cluster, out_dir_any)

                if len(roots_in_cluster) == root_count:
                    detailed_all.append(rec)
                    copied_all += copy_cluster(cluster, out_dir_all)

    # Write per-category mapping index
    index_payload = {
        "category": category,
        "roots": [{"index": i, "label": labels[i], "path": roots[i]} for i in range(root_count)],
        "require_identical_content": REQUIRE_IDENTICAL_CONTENT,
        "content_compare_mode": CONTENT_COMPARE_MODE,
        "ignore_order_in_content": IGNORE_ORDER_IN_CONTENT,
        "counts": {
            "total_yaml_seen": len(entries) + skipped_missing_meta,
            "usable_yaml": len(entries),
            "skipped_missing_name_or_identifier": skipped_missing_meta,
            "distinct_name_identifier_pairs": len(groups),
            "groups_any": len(detailed_any),
            "groups_all_roots": len(detailed_all),
            "files_copied_any": copied_any,
            "files_copied_all_roots": copied_all
        },
        "groups_any": detailed_any,         # full mapping: which files from which roots
        "groups_all_roots": detailed_all    # subset that spans every root
    }
    index_path = os.path.join(out_base, category, "common_index.yaml")
    write_yaml(index_path, index_payload)

    # Return stats for the top-level report
    return {
        "category": category,
        "index_file": index_path,
        "roots": [{"label": labels[i], "path": roots[i]} for i in range(root_count)],
        "counts": index_payload["counts"]
    }

def write_yaml(path: str, data: Any):
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)

def main():
    ensure_dir(OUTPUT_BASE)
    if CLEAN_DEST:
        clean_folder(os.path.join(OUTPUT_BASE, "services"))
        clean_folder(os.path.join(OUTPUT_BASE, "pipelines"))

    services_stats  = process_category("services",  SERVICES_DIRS,  OUTPUT_BASE)
    pipelines_stats = process_category("pipelines", PIPELINES_DIRS, OUTPUT_BASE)

    report = {
        "output_base": OUTPUT_BASE,
        "matching_basis": "Common when YAML share the same (name, identifier) AND identical content.",
        "config": {
            "case_insensitive": CASE_INSENSITIVE_COMPARE,
            "require_both_fields": REQUIRE_BOTH_FIELDS,
            "require_identical_content": REQUIRE_IDENTICAL_CONTENT,
            "content_compare_mode": CONTENT_COMPARE_MODE,
            "ignore_order_in_content": IGNORE_ORDER_IN_CONTENT,
            "field_paths": FIELD_PATHS,
        },
        "services": services_stats,
        "pipelines": pipelines_stats,
        "notes": [
            "See services/common_index.yaml and pipelines/common_index.yaml for exact file mappings.",
            "One representative per root is copied for each common cluster.",
            "Items present in every root are also copied to the 'all_roots' subfolder."
        ]
    }
    write_yaml(os.path.join(OUTPUT_BASE, "common_report.yaml"), report)

    print("Done.")
    print(f"  Services  -> {os.path.join(OUTPUT_BASE, 'services')}")
    print(f"    Index   -> {os.path.join(OUTPUT_BASE, 'services', 'common_index.yaml')}")
    print(f"    All-roots subset -> {os.path.join(OUTPUT_BASE, 'services', 'all_roots')}")
    print(f"  Pipelines -> {os.path.join(OUTPUT_BASE, 'pipelines')}")
    print(f"    Index   -> {os.path.join(OUTPUT_BASE, 'pipelines', 'common_index.yaml')}")
    print(f"    All-roots subset -> {os.path.join(OUTPUT_BASE, 'pipelines', 'all_roots')}")
    print(f"  Report    -> {os.path.join(OUTPUT_BASE, 'common_report.yaml')}")

if __name__ == "__main__":
    main()