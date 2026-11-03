"""Add editable mathematical formulas and algorithm tables to the v7 manuscript."""

from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from docx.text.paragraph import Paragraph


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "QScope_Research_Paper_Rithvik_Illustrated_v7.docx"
OUTPUT = ROOT / "QScope_Research_Paper_Rithvik_Illustrated_v8.docx"
INK = "16243A"
BLUE = "4E8EF7"
NAVY = "16243A"


def margins(cell, top=90, start=120, bottom=90, end=120):
    props = cell._tc.get_or_add_tcPr()
    block = props.first_child_found_in("w:tcMar")
    if block is None:
        block = OxmlElement("w:tcMar")
        props.append(block)
    for side, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = block.find(qn(f"w:{side}"))
        if node is None:
            node = OxmlElement(f"w:{side}")
            block.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def anchor_paragraph(doc, needle):
    for paragraph in doc.paragraphs:
        if needle in paragraph.text:
            return paragraph
    raise ValueError(f"Missing insertion anchor: {needle}")


def insert_table_after(doc, anchor, table):
    p = anchor_paragraph(doc, anchor)
    table._tbl.getparent().remove(table._tbl)
    p._p.addnext(table._tbl)


def formula_table(doc, anchor, title, expression, explanation):
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    cell = table.cell(0, 0)
    cell.width = Inches(6.85)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    cell.text = ""
    margins(cell, 95, 140, 95, 140)
    shade = OxmlElement("w:shd")
    shade.set(qn("w:fill"), "EFF5FF")
    cell._tc.get_or_add_tcPr().append(shade)
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(title)
    r.bold = True
    r.font.name = "Aptos"
    r.font.size = Pt(9)
    r.font.color.rgb = RGBColor.from_string(BLUE)
    p = cell.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run(expression)
    r.font.name = "Cambria Math"
    r.font.size = Pt(11)
    r.font.color.rgb = RGBColor.from_string(INK)
    p = cell.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    r = p.add_run(explanation)
    r.font.name = "Aptos"
    r.font.size = Pt(8.5)
    r.font.color.rgb = RGBColor.from_string(INK)
    insert_table_after(doc, anchor, table)


def algorithm_table(doc, anchor, title, input_text, steps, output_text):
    table = doc.add_table(rows=len(steps) + 3, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    widths = (0.8, 6.05)
    for row in table.rows:
        row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
        for i, cell in enumerate(row.cells):
            cell.width = Inches(widths[i])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            margins(cell, 60, 90, 60, 90)
    title_cell = table.cell(0, 0).merge(table.cell(0, 1))
    title_cell.text = title
    shade = OxmlElement("w:shd")
    shade.set(qn("w:fill"), NAVY)
    title_cell._tc.get_or_add_tcPr().append(shade)
    for r in title_cell.paragraphs[0].runs:
        r.bold = True
        r.font.name = "Aptos"
        r.font.size = Pt(9.5)
        r.font.color.rgb = RGBColor(255, 255, 255)
    entries = [("Input", input_text)]
    entries.extend((f"Step {i}", step) for i, step in enumerate(steps, 1))
    entries.append(("Output", output_text))
    for row_i, (label, text) in enumerate(entries, start=1):
        for col_i, value in enumerate((label, text)):
            cell = table.cell(row_i, col_i)
            cell.text = value
            shade = OxmlElement("w:shd")
            shade.set(qn("w:fill"), "EFF5FF" if row_i % 2 else "F8FAFC")
            cell._tc.get_or_add_tcPr().append(shade)
            for p in cell.paragraphs:
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.keep_together = True
                for r in p.runs:
                    r.font.name = "Aptos"
                    r.font.size = Pt(8.5)
                    r.font.color.rgb = RGBColor.from_string(INK)
        for r in table.cell(row_i, 0).paragraphs[0].runs:
            r.bold = True
            r.font.color.rgb = RGBColor.from_string(BLUE)
    insert_table_after(doc, anchor, table)


def main():
    if not SOURCE.exists():
        raise FileNotFoundError(SOURCE)
    if OUTPUT.exists():
        raise FileExistsError(f"Refusing to overwrite: {OUTPUT}")
    doc = Document(SOURCE)

    formula_table(doc, "For a pure n-qubit state", "Normalized state vector and raw memory", "|ψ⟩ = Σᵢ₌₀⁽²ⁿ⁻¹⁾ αᵢ|i⟩     Σᵢ|αᵢ|² = 1     Mₛᵥ = 16 × 2ⁿ bytes", "αᵢ are complex amplitudes. Sixteen bytes is the storage per complex128 value; this is raw array storage before temporary arrays.")
    formula_table(doc, "A dense density matrix stores", "Density matrix and raw memory", "ρ = |ψ⟩⟨ψ|     Tr(ρ) = 1     M_dm = 16 × 4ⁿ bytes", "An n-qubit density matrix has 2ⁿ rows and columns. Mixed states have Tr(ρ²) ≤ 1; pure states have Tr(ρ²) = 1.")
    formula_table(doc, "The planner compares the peak estimate", "Preflight memory condition", "M_peak = 3 × M_representation     Proceed only if M_peak ≤ B", "B is the configured budget. The factor of three models working copies in QScope's planner; it is an estimate and not a strict operating-system memory limit.")
    formula_table(doc, "The trace service records the state", "Measurement probabilities and finite-shot uncertainty", "p(x) = |⟨x|ψ⟩|²     f̂(x) = Nₓ/S     SE[f̂] ≈ √(p(x)(1−p(x))/S)", "Nₓ is the number of observations of outcome x in S shots. The standard error is an approximation for independent samples; QScope's simulator outputs counts and probabilities.")
    formula_table(doc, "state metrics, comparisons, and what-if results", "State purity and von Neumann entropy", "Purity(ρ) = Tr(ρ²)     S(ρ) = −Tr(ρ log₂ρ)", "Purity is 1 for a pure state and below 1 for a mixed state. Entropy is computed from the eigenvalues of ρ and is expressed in bits.")
    formula_table(doc, "QScope includes a parameterized QAOA", "QAOA Max-Cut cost", "C(z) = Σ_(u,v)∈E wᵤᵥ [zᵤ ≠ zᵥ]     ⟨C⟩ = ⟨ψ(γ,β)|Ĉ|ψ(γ,β)⟩", "The cut value sums weights of edges whose endpoint bits differ. The parameterized circuit alternates cost and mixer operations; parameter search does not guarantee a global optimum.")

    algorithm_table(doc, "Before a run, QScope estimates", "Algorithm 1. Resource-aware single-run execution", "Validated circuit C, run options O, configured memory budget B.", [
        "Read the qubit count, noise model, requested backend, shots, and seed.",
        "Select or validate the representation: state vector for ideal evolution; density matrix for supported exact noisy evolution when feasible; trajectory sampling when noisy exact evolution is too costly.",
        "Estimate raw and peak working memory for the selected representation and compare the peak with B and backend limits.",
        "If incompatible or over budget, return an actionable blocked plan without starting the simulation.",
        "Otherwise execute using the selected backend, shots, noise settings, and seed; collect counts, probabilities, metrics, timing, and memory observations.",
        "Attach the plan, simulation label, settings, warnings, and provenance to the returned result.",
    ], "A labelled simulation result with provenance, or an explicit refusal with resource estimates.")
    algorithm_table(doc, "For each job the API supplies a planned peak-memory estimate", "Algorithm 2. Memory-bounded batch scheduling", "Ordered jobs J, estimated peaks mⱼ, shared budget B, worker cap W.", [
        "Start a wave with the next unassigned job in input order.",
        "Add following jobs while worker count ≤ W and the sum of estimated peaks ≤ B.",
        "If a single job exceeds B, still send it through the normal planner so it receives the standard refusal and estimate.",
        "Run a one-job wave directly; run multiple jobs in a wave concurrently.",
        "Store each result in its original input position, independent of completion order.",
        "Repeat until every job has a result or planner refusal.",
    ], "Results in original job order; concurrent waves respect the estimated shared-memory budget where feasible.")
    doc.core_properties.title = doc.core_properties.title
    doc.core_properties.subject = "Original v7 manuscript with additional editable mathematical formulas and algorithm tables"
    doc.save(OUTPUT)
    print(f"Wrote {OUTPUT}")
    print(f"Tables: {len(doc.tables)}; embedded images retained: {len(doc.inline_shapes)}")


if __name__ == "__main__":
    main()
