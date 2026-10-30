"""Executes notebooks/analysis_notebook.py cell by cell and writes notebooks/analysis.ipynb with real outputs (stdout, tables, figures).
Needed because Jupyter may not be installed; the resulting file is a standard nbformat-4 notebook."""
import base64, io, json, re, sys, contextlib, traceback, os
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.chdir(HERE)
src = (HERE / "analysis_notebook.py").read_text()
cells = re.split(r"^# %%", src, flags=re.M)[1:]
ns = {"__name__": "__main__"}
displayed = []


def display(obj):
    displayed.append(obj)


import types
mod = types.ModuleType("IPython.display"); mod.display = display
ns["display"] = display   # real notebooks import it from IPython; here we capture it

nb = {"cells": [], "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}, "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
count = 0
for c in cells:
    is_md = c.startswith(" [markdown]")
    body = c.split("\n", 1)[1] if "\n" in c else ""
    if is_md:
        text = "\n".join(l[2:] if l.startswith("# ") else l.lstrip("#") for l in body.strip("\n").split("\n"))
        nb["cells"].append({"cell_type": "markdown", "metadata": {}, "source": text.splitlines(True), "id": f"md{len(nb['cells'])}"})
        continue
    code = body.strip("\n")
    count += 1
    outputs, buf = [], io.StringIO()
    displayed.clear()
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(re.sub(r"^from IPython\.display import display\n?", "", code, flags=re.M), f"cell{count}", "exec"), ns)
    except Exception:
        buf.write(traceback.format_exc())
        print("ERROR in cell", count, traceback.format_exc(), file=sys.stderr)
    if buf.getvalue():
        outputs.append({"output_type": "stream", "name": "stdout", "text": buf.getvalue().splitlines(True)})
    for obj in displayed:
        if isinstance(obj, (pd.DataFrame, pd.Series)):
            df = obj.to_frame() if isinstance(obj, pd.Series) else obj
            outputs.append({"output_type": "display_data", "metadata": {}, "data": {"text/plain": df.to_string(max_rows=60, max_colwidth=160).splitlines(True), "text/html": df.to_html(max_rows=60, max_cols=30).splitlines(True)}})
        else:
            outputs.append({"output_type": "display_data", "metadata": {}, "data": {"text/plain": [str(obj)]}})
    for num in plt.get_fignums():
        fig = plt.figure(num); b = io.BytesIO(); fig.savefig(b, format="png", dpi=90, bbox_inches="tight")
        outputs.append({"output_type": "display_data", "metadata": {}, "data": {"image/png": base64.b64encode(b.getvalue()).decode(), "text/plain": ["<Figure>"]}})
    plt.close("all")
    nb["cells"].append({"cell_type": "code", "metadata": {}, "execution_count": count, "source": code.splitlines(True), "outputs": outputs, "id": f"c{count}"})
(HERE / "analysis.ipynb").write_text(json.dumps(nb, indent=1))
errs = sum(1 for c in nb["cells"] if c["cell_type"] == "code" and any("Traceback" in "".join(o.get("text", [])) for o in c["outputs"] if o["output_type"] == "stream"))
print(f"notebook written: {len(nb['cells'])} cells, {count} code cells, {errs} with errors")
sys.exit(1 if errs else 0)
