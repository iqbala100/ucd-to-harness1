import os
import re
import shutil
import hashlib
import yaml
from typing import Any, Dict, List, Tuple, Optional, DefaultDict
from collections import defaultdict
from itertools import combinations

# ========== CONFIG ==========
# Multiple input roots to scan recursively
input_dirs = [
    r"C:\Users\hiiqb\Desktop\ucd-compare\ucd-to-harness1\harness_out_RG1\.harness",
    r"C:\Users\hiiqb\Desktop\ucd-compare\ucd-to-harness1\harness_out_RG2\.harness",
    r"C:\Users\hiiqb\Desktop\ucd-compare\ucd-to-harness1\harness_out_RG3\.harness",
    r"C:\Users\hiiqb\Desktop\ucd-compare\ucd-to-harness1\harness_out_RG4\.harness",
    r"C:\Users\hiiqb\Desktop\ucd-compare\ucd-to-harness1\harness_out_RG5\.harness",
    r"C:\Users\hiiqb\Desktop\ucd-compare\ucd-to-harness1\harness_out_RG6\.harness",
]

# Base destination; all outputs are created under this
matching_common_folder = r"C:\Users\hiiqb\Desktop\ucd-compare\ucd-to-harness1\yaml_matching_common1"

# --- Metadata match rules (PRIMARY) ---
REQUIRE_SAME_NAME = True          # require YAML 'name' equality
REQUIRE_SAME_IDENTIFIER = True    # require YAML 'identifier' equality

# Tags matching mode:
#   'any'     -> at least 1 tag in common
#   'min'     -> at least TAGS_INTERSECT_MIN in common
#   'subset'  -> tags of one file ⊆ tags of the other
#   'exact'   -> sets equal (ignoring order)
TAGS_MATCH_MODE = "any"
TAGS_INTERSECT_MIN = 1            # used when TAGS_MATCH_MODE == 'min'
TAGS_REQUIRED = False             # if True, both files must have non-empty tags

# Normalize comparisons
CASE_INSENSITIVE_COMPARE = True   # lowercases name, identifier, tag keys/values

# Where to look for fields inside YAML (first hit wins)
FIELD_PATHS = {
    "name":       ["service.name", "name", "metadata.name"],
    "identifier": ["service.identifier", "identifier", "metadata.identifier", "id"],
    "tags":       ["service.tags", "tags", "metadata.tags"]
}

# --- Optional content check (SECONDARY) ---
ENABLE_CONTENT_CHECK = False      # set True to also check content with DeepDiff
CONTENT_MODE = "exact"            # 'exact' or 'threshold'
SIMILARITY_THRESHOLD = 0.90       # used when CONTENT_MODE == 'threshold'

# Pre-filter: compare only files that share the same filename across roots
MATCH_BY_FILENAME = False

# Copy layout options
PRESERVE_STRUCTURE = False        # mirror source subfolders; if False, flatten with safe names

# Clear destination before copying
CLEAN_DEST = False

# OUTPUT SWITCHES (turn on/off the buckets you need)
WRITE_PER_ROOT_COMMON_ANY = True
WRITE_PER_ROOT_COMMON_ALL = True
WRITE_PER_ROOT_UNIQUE     = True

WRITE_GLOBAL_COMMON_ANY   = True
WRITE_GLOBAL_COMMON_ALL   = True

WRITE_PAIRWISE_COMMON     = True

# Report name (simple YAML summaries)
REPORT_NAME = "matches_report.yaml"
# ========== END CONFIG ==========

# ---- Optional DeepDiff usage (only if ENABLE_CONTENT_CHECK is True) ----
try:
    from deepdiff import DeepDiff  # noqa
except Exception:
    if ENABLE_CONTENT_CHECK:
        raise RuntimeError("DeepDiff required: pip install deepdiff")


# ================= helpers =================
def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def list_yaml_files_recursively(root_dir: str) -> List[Tuple[str, str]]:
    files = []
    for root, _, filenames in os.walk(root_dir):
        for name in filenames:
            if name.lower().endswith((".yaml", ".yml")):
                full = os.path.join(root, name)
                rel = os.path.relpath(full, root_dir)
                files.append((full, rel))
    return files

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

def normalize_tags(raw: Any) -> List[str]:
    out = []
    if raw is None:
        return out
    if isinstance(raw, dict):
        for k, v in raw.items():
            k2 = norm_str(k)
            v2 = "" if v is None else norm_str(v)
            out.append(f"{k2}={v2}")
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                for k, v in item.items():
                    k2 = norm_str(k)
                    v2 = "" if v is None else norm_str(v)
                    out.append(f"{k2}={v2}")
            else:
                out.append(norm_str(item))
    else:
        out.append(norm_str(raw))
    # dedupe preserve order
    seen, dedup = set(), []
    for t in out:
        if t not in seen:
            seen.add(t)
            dedup.append(t)
    return dedup

def extract_metadata(doc: Any) -> Dict[str, Any]:
    name = find_first(doc, FIELD_PATHS["name"])
    ident = find_first(doc, FIELD_PATHS["identifier"])
    tags = find_first(doc, FIELD_PATHS["tags"])
    return {
        "name": norm_str(name),
        "identifier": norm_str(ident),
        "tags": normalize_tags(tags),
    }

def tags_match(tags_a: List[str], tags_b: List[str]) -> Tuple[bool, Dict[str, Any]]:
    set_a, set_b = set(tags_a), set(tags_b)
    inter = sorted(list(set_a & set_b))
    if TAGS_REQUIRED and (not set_a or not set_b):
        return (False, {"reason": "tags_required_missing", "shared": []})
    if TAGS_MATCH_MODE == "any":
        return (len(inter) >= 1, {"shared": inter})
    if TAGS_MATCH_MODE == "min":
        return (len(inter) >= TAGS_INTERSECT_MIN, {"shared": inter})
    if TAGS_MATCH_MODE == "subset":
        ok = set_a.issubset(set_b) or set_b.issubset(set_a)
        return (ok, {"shared": inter})
    if TAGS_MATCH_MODE == "exact":
        ok = set_a == set_b
        return (ok, {"shared": inter})
    return (len(inter) >= 1, {"shared": inter})

def metadata_match(meta_a: Dict[str, Any], meta_b: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    reasons = []
    if REQUIRE_SAME_NAME:
        if not (meta_a["name"] and meta_b["name"] and meta_a["name"] == meta_b["name"]):
            return (False, {"reason": "name_mismatch", "a": meta_a["name"], "b": meta_b["name"]})
        reasons.append("name_eq")
    if REQUIRE_SAME_IDENTIFIER:
        if not (meta_a["identifier"] and meta_b["identifier"] and meta_a["identifier"] == meta_b["identifier"]):
            return (False, {"reason": "identifier_mismatch", "a": meta_a["identifier"], "b": meta_b["identifier"]})
        reasons.append("identifier_eq")
    ok, info = tags_match(meta_a["tags"], meta_b["tags"])
    if not ok:
        info.setdefault("reason", "tags_mismatch")
        return (False, info)
    reasons.append(f"tags_{TAGS_MATCH_MODE}")
    return (True, {"reason": "metadata_match", "shared_tags": info.get("shared", []), "checks": reasons})

def flatten(obj, path=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from flatten(v, path + (str(k),))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from flatten(v, path + (f"[{i}]",))
    else:
        key = ".".join(path) if path else "<root>"
        yield (key, obj)

def similarity(flat1: Dict[str, Any], flat2: Dict[str, Any]) -> float:
    set1 = set(flat1.items())
    set2 = set(flat2.items())
    if not set1 and not set2:
        return 1.0
    union = set1 | set2
    inter = set1 & set2
    return len(inter) / len(union) if union else 0.0

def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def sane_name(s: str) -> str:
    s = s.replace(os.sep, "__")
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)

def build_dest_base(base: str, rel_p: str, root_label: str, preserve: bool) -> str:
    if preserve:
        dst = os.path.join(base, root_label, rel_p)
        ensure_dir(os.path.dirname(dst))
        return dst
    safe = sane_name(rel_p)
    dst = os.path.join(base, f"{root_label}__{safe}")
    root, ext = os.path.splitext(dst)
    if not ext:
        dst = root + ".yaml"
    return dst

def write_yaml(path: str, data: Any):
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)

# ================= main =================
def main():
    if not input_dirs or len(input_dirs) < 2:
        print("Provide at least two input directories in 'input_dirs'.")
        return

    # Prepare destinations
    if CLEAN_DEST and os.path.isdir(matching_common_folder):
        for root, dirs, files in os.walk(matching_common_folder, topdown=False):
            for name in files:
                try: os.remove(os.path.join(root, name))
                except Exception: pass
            for name in dirs:
                try: os.rmdir(os.path.join(root, name))
                except Exception: pass
    ensure_dir(matching_common_folder)

    # Collect files: (root_idx, label, root, abs, rel, meta)
    entries: List[Dict[str, Any]] = []
    labels: List[str] = []
    for idx, root in enumerate(input_dirs):
        label = os.path.basename(os.path.normpath(root)) or f"root{idx+1}"
        labels.append(label)
        for abs_p, rel_p in list_yaml_files_recursively(root):
            try:
                doc = load_first_yaml_doc(abs_p) or {}
            except Exception:
                continue
            meta = extract_metadata(doc)
            entries.append({
                "root_idx": idx,
                "label": label,
                "root": root,
                "abs": abs_p,
                "rel": rel_p,
                "meta": meta,
                "filename": os.path.basename(rel_p),
            })
    if len(entries) < 2:
        print("No YAML files found.")
        return

    # Group by (name,identifier) key
    def key_of(meta: Dict[str, Any]) -> Optional[Tuple[Optional[str], Optional[str]]]:
        if REQUIRE_SAME_NAME and REQUIRE_SAME_IDENTIFIER:
            return (meta["name"], meta["identifier"])
        if REQUIRE_SAME_NAME:
            return (meta["name"], None)
        if REQUIRE_SAME_IDENTIFIER:
            return (None, meta["identifier"])
        return None

    groups: DefaultDict[Tuple[Optional[str], Optional[str]], List[Dict[str, Any]]] = defaultdict(list)
    for e in entries:
        k = key_of(e["meta"])
        if k is not None:
            groups[k].append(e)

    # Optional filename pre-filter inside each group
    if MATCH_BY_FILENAME:
        new_groups: DefaultDict[Tuple[Optional[str], Optional[str]], List[Dict[str, Any]]] = defaultdict(list)
        for k, items in groups.items():
            buckets: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
            for it in items:
                buckets[it["filename"]].append(it)
            for _, blist in buckets.items():
                if len(blist) > 1:
                    new_groups[k].extend(blist)
        groups = new_groups

    # Helper to check tags (and optional content) between two entries
    def entries_match(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
        ok, _ = metadata_match(a["meta"], b["meta"])
        if not ok:
            return False
        if ENABLE_CONTENT_CHECK:
            if CONTENT_MODE == "exact":
                diff = DeepDiff(load_first_yaml_doc(a["abs"]) or {}, load_first_yaml_doc(b["abs"]) or {}, ignore_order=True)
                return not diff
            else:
                flat1 = dict(flatten(load_first_yaml_doc(a["abs"]) or {}))
                flat2 = dict(flatten(load_first_yaml_doc(b["abs"]) or {}))
                return similarity(flat1, flat2) >= SIMILARITY_THRESHOLD
        return True

    # Derive relationship sets
    root_count = len(input_dirs)
    key_present_in_root: DefaultDict[Tuple[Optional[str], Optional[str]], set] = defaultdict(set)
    pairwise_keys: DefaultDict[Tuple[str, str], set] = defaultdict(set)  # (labelA,labelB) -> set(keys)

    # Per-root file buckets
    per_root_common_any: DefaultDict[str, set] = defaultdict(set)
    per_root_common_all: DefaultDict[str, set] = defaultdict(set)
    per_root_all_keys: DefaultDict[int, set] = defaultdict(set)  # for unique calc

    for k, items in groups.items():
        # Track which roots have this key at all
        roots_with_key = {it["root_idx"] for it in items}
        for idx in roots_with_key:
            per_root_all_keys[idx].add(k)

        # Build pairwise matches for this key based on tags/content rules
        for a, b in combinations(items, 2):
            if a["root_idx"] == b["root_idx"]:
                continue
            if entries_match(a, b):
                pair_label = tuple(sorted([a["label"], b["label"]]))
                pairwise_keys[pair_label].add(k)
                # common_any per root
                per_root_common_any[a["label"]].add(a["abs"])
                per_root_common_any[b["label"]].add(b["abs"])
                key_present_in_root[k].update({a["root_idx"], b["root_idx"]})

    # Keys common to ALL roots (respecting tags/content via pairwise matches)
    common_all_keys = set()
    for k, roots in key_present_in_root.items():
        if len(roots) == root_count:
            # sanity: ensure for this key, every root has at least one file matched with the others
            # (already implied by pairwise building; we accept it)
            common_all_keys.add(k)

    # Fill per_root_common_all (choose any file for that key from that root)
    by_root_by_key: DefaultDict[Tuple[int, Tuple[Optional[str], Optional[str]]], List[Dict[str, Any]]] = defaultdict(list)
    for k, items in groups.items():
        for it in items:
            by_root_by_key[(it["root_idx"], k)].append(it)

    for k in common_all_keys:
        for idx in range(root_count):
            candidates = by_root_by_key.get((idx, k), [])
            if candidates:
                it = candidates[0]  # first is fine
                per_root_common_all[it["label"]].add(it["abs"])

    # Unique: keys present only in a single root (no cross-root matches & no presence elsewhere)
    unique_by_root: DefaultDict[str, set] = defaultdict(set)
    # count how many roots each key appears in (regardless of tags/content)
    simple_presence_count: DefaultDict[Tuple[Optional[str], Optional[str]], set] = defaultdict(set)
    for k, items in groups.items():
        simple_presence_count[k] = {it["root_idx"] for it in items}
    for idx in range(root_count):
        label = labels[idx]
        for k in per_root_all_keys[idx]:
            if len(simple_presence_count[k]) == 1:
                # pick an arbitrary file for this key in this root
                candidates = by_root_by_key.get((idx, k), [])
                if candidates:
                    unique_by_root[label].add(candidates[0]["abs"])

    # -------- COPY PHASE --------
    def copy_many(paths: List[str], base: str, label: str):
        ensure_dir(base)
        seen_hashes = set()
        copied = 0
        for abs_p in sorted(paths):
            # find rel path and label for naming
            entry = next((e for e in entries if e["abs"] == abs_p), None)
            if not entry:
                continue
            rel = entry["rel"]
            root_label = label if label else entry["label"]
            try:
                h = file_sha256(abs_p)
            except Exception:
                h = f"path::{abs_p}"
            if h in seen_hashes:
                continue
            seen_hashes.add(h)
            dst = build_dest_base(base, rel, root_label, PRESERVE_STRUCTURE)
            ensure_dir(os.path.dirname(dst))
            shutil.copy2(abs_p, dst)
            copied += 1
        return copied

    # Per-root outputs
    per_root_summary: Dict[str, Dict[str, int]] = {}
    for label in labels:
        per_root_summary[label] = {}
        # common_any
        if WRITE_PER_ROOT_COMMON_ANY:
            base = os.path.join(matching_common_folder, "per_root", label, "common_any")
            per_root_summary[label]["common_any"] = copy_many(list(per_root_common_any[label]), base, label)
        # common_all
        if WRITE_PER_ROOT_COMMON_ALL:
            base = os.path.join(matching_common_folder, "per_root", label, "common_all")
            per_root_summary[label]["common_all"] = copy_many(list(per_root_common_all[label]), base, label)
        # unique
        if WRITE_PER_ROOT_UNIQUE:
            base = os.path.join(matching_common_folder, "per_root", label, "unique")
            per_root_summary[label]["unique"] = copy_many(list(unique_by_root[label]), base, label)

    # Global outputs
    if WRITE_GLOBAL_COMMON_ANY:
        base = os.path.join(matching_common_folder, "global_common_any")
        all_paths = set()
        for s in per_root_common_any.values():
            all_paths.update(s)
        copy_many(list(all_paths), base, "")  # label comes from entry

    if WRITE_GLOBAL_COMMON_ALL:
        base = os.path.join(matching_common_folder, "global_common_all")
        all_paths = set()
        for s in per_root_common_all.values():
            all_paths.update(s)
        copy_many(list(all_paths), base, "")

    # Pairwise outputs
    pairwise_summary: Dict[str, int] = {}
    if WRITE_PAIRWISE_COMMON:
        for (la, lb), keys in pairwise_keys.items():
            base = os.path.join(matching_common_folder, "pairwise", f"{la}__{lb}")
            # collect actual files for these keys from both roots
            paths = []
            for k in keys:
                # pick any file from la with key k
                idx_a = labels.index(la)
                idx_b = labels.index(lb)
                if (idx_a, k) in by_root_by_key:
                    paths.append(by_root_by_key[(idx_a, k)][0]["abs"])
                if (idx_b, k) in by_root_by_key:
                    paths.append(by_root_by_key[(idx_b, k)][0]["abs"])
            pairwise_summary[f"{la}__{lb}"] = copy_many(paths, base, "")

    # Simple YAML report
    report = {
        "config": {
            "require_same_name": REQUIRE_SAME_NAME,
            "require_same_identifier": REQUIRE_SAME_IDENTIFIER,
            "tags_match_mode": TAGS_MATCH_MODE,
            "tags_intersect_min": TAGS_INTERSECT_MIN,
            "tags_required": TAGS_REQUIRED,
            "case_insensitive": CASE_INSENSITIVE_COMPARE,
            "field_paths": FIELD_PATHS,
            "match_by_filename": MATCH_BY_FILENAME,
            "preserve_structure": PRESERVE_STRUCTURE,
            "enable_content_check": ENABLE_CONTENT_CHECK,
            "content_mode": CONTENT_MODE if ENABLE_CONTENT_CHECK else "none",
            "similarity_threshold": SIMILARITY_THRESHOLD if (ENABLE_CONTENT_CHECK and CONTENT_MODE == 'threshold') else None,
        },
        "stats": {
            "roots": labels,
            "pairwise_buckets": sorted(list(pairwise_keys.keys())),
        },
        "per_root_summary": per_root_summary,
        "pairwise_summary": pairwise_summary,
    }
    write_yaml(os.path.join(matching_common_folder, REPORT_NAME), report)

    print("Done.")
    print(f"  Roots: {len(labels)}")
    print(f"  Wrote per-root buckets under: {os.path.join(matching_common_folder, 'per_root')}")
    if WRITE_GLOBAL_COMMON_ANY:
        print(f"  Global any : {os.path.join(matching_common_folder, 'global_common_any')}")
    if WRITE_GLOBAL_COMMON_ALL:
        print(f"  Global all : {os.path.join(matching_common_folder, 'global_common_all')}")
    if WRITE_PAIRWISE_COMMON:
        print(f"  Pairwise   : {os.path.join(matching_common_folder, 'pairwise')}")
    print(f"  Report     : {os.path.join(matching_common_folder, REPORT_NAME)}")


if __name__ == "__main__":
    main()