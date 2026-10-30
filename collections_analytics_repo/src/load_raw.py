"""Layer 0 - RAW. Loads every CSV byte-for-byte as TEXT into raw_<table> (no cleaning, no typing).
Also writes a SHA-256 manifest so raw immutability can be verified by tests."""
import hashlib, json, sqlite3
import pandas as pd
from .config import RAW_DIR, DB_PATH, RAW_TABLES, REPORTS_DIR


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_raw(db_path=DB_PATH, raw_dir=RAW_DIR):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    manifest = {}
    for t in RAW_TABLES:
        f = raw_dir / f"{t}.csv"
        # dtype=str + keep_default_na=False then '' -> None : preserves text exactly, nulls are real nulls
        df = pd.read_csv(f, dtype=str, keep_default_na=False)
        df = df.replace({"": None})
        df.to_sql(f"raw_{t}", con, index=False, if_exists="replace")
        manifest[f"{t}.csv"] = {"sha256": sha256(f), "rows": len(df)}
    con.commit()
    con.close()
    REPORTS_DIR.mkdir(exist_ok=True)
    (REPORTS_DIR / "raw_manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":
    m = load_raw()
    for k, v in m.items():
        print(f"{k:32s} {v['rows']:>8,d}  {v['sha256'][:12]}")
