"""Generate the QScope project proposal document."""

from pathlib import Path
import re

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "QScope_Project_Proposal.docx"

ABSTRACT = (
    "Quantum computing is difficult to explore when circuit construction, simulation, debugging, analysis, and "
    "reporting are scattered across separate tools and technical workflows. QScope is proposed as a local-first "
    "quantum computing workspace that helps students, researchers, and developers move from a question to an "
    "explainable experiment on an ordinary computer. Its current Python engine uses NumPy to simulate quantum "
    "circuits with statevector, density-matrix, and trajectory representations, while a web interface supports "
    "circuit building, OpenQASM import, measurement, gate-by-gate tracing, analysis, optimization, noise studies, "
    "experiments, benchmarks, and research reports. A grounded assistant can explain available circuit and run "
    "data, including when evidence is insufficient; optional language-model narration is separate from computed "
    "results. The project addresses a usability gap: powerful frameworks expose substantial capability but can "
    "require programming knowledge and movement between interfaces. QScope’s objective is to make the complete "
    "learning and investigation loop approachable without hiding technical detail or misrepresenting classical "
    "simulation as quantum hardware. The proposed development prioritizes a chat-like entry point, visual state "
    "explanations, reproducible project history, safe resource limits, and straightforward installation. Future "
    "work may add richer algorithm lessons, accessible desktop packaging, optional hardware connections, and "
    "guided application templates. QScope aims to become a practical bridge between quantum concepts and "
    "hands-on experimentation, while remaining transparent, offline-capable, and useful for deeper research."
)


def shade(cell, fill: str) -> None:
    properties = cell._tc.get_or_add_tcPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), fill)
    properties.append(shading)


def set_cell_text(cell, text: str, *, bold=False, color="243047", size=9.5) -> None:
    cell.text = ""
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_after = Pt(3)
    run = paragraph.add_run(text)
    run.bold = bold
    run.font.name = "Aptos"
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor.from_string(color)


def add_bullet(document: Document, text: str) -> None:
    paragraph = document.add_paragraph(style="List Bullet")
    paragraph.paragraph_format.space_after = Pt(4)
    paragraph.add_run(text)


def add_numbered(document: Document, text: str) -> None:
    paragraph = document.add_paragraph(style="List Number")
    paragraph.paragraph_format.space_after = Pt(4)
    paragraph.add_run(text)


def add_hyperlink(paragraph, label: str, url: str) -> None:
    relationship = paragraph.part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), relationship)
    run = OxmlElement("w:r")
    properties = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "087F8C")
    properties.append(color)
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    properties.append(underline)
    run.append(properties)
    text = OxmlElement("w:t")
    text.text = label
    run.append(text)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def main() -> None:
    word_count = len(re.findall(r"\b[\w’'-]+\b", ABSTRACT))
    if word_count != 200:
        raise ValueError(f"Abstract must be exactly 200 words; got {word_count}.")

    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(0.72)
    section.bottom_margin = Inches(0.72)
    section.left_margin = Inches(0.82)
    section.right_margin = Inches(0.82)

    styles = document.styles
    normal = styles["Normal"]
    normal.font.name = "Aptos"
    normal.font.size = Pt(10)
    normal.font.color.rgb = RGBColor(41, 52, 70)
    normal.paragraph_format.space_after = Pt(7)
    normal.paragraph_format.line_spacing = 1.12
    for style_name, size, color in [("Heading 1", 16, "087F8C"), ("Heading 2", 12, "5046A5")]:
        style = styles[style_name]
        style.font.name = "Aptos Display"
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor.from_string(color)
        style.paragraph_format.space_before = Pt(12)
        style.paragraph_format.space_after = Pt(5)

    header = section.header.paragraphs[0]
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    header_run = header.add_run("QSCOPE  /  PROJECT PROPOSAL")
    header_run.font.name = "Aptos"
    header_run.font.size = Pt(8)
    header_run.font.bold = True
    header_run.font.color.rgb = RGBColor(8, 127, 140)

    title = document.add_paragraph()
    title.paragraph_format.space_before = Pt(25)
    title.paragraph_format.space_after = Pt(3)
    run = title.add_run("QScope")
    run.font.name = "Aptos Display"
    run.font.size = Pt(34)
    run.font.bold = True
    run.font.color.rgb = RGBColor(26, 35, 58)

    subtitle = document.add_paragraph()
    subtitle.paragraph_format.space_after = Pt(14)
    run = subtitle.add_run("A local-first, explainable quantum computing workspace")
    run.font.size = Pt(14)
    run.font.color.rgb = RGBColor(8, 127, 140)

    intro = document.add_paragraph()
    intro.paragraph_format.space_after = Pt(14)
    run = intro.add_run("PROJECT ABSTRACT  ·  200 WORDS")
    run.bold = True
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(80, 70, 165)

    abstract_paragraph = document.add_paragraph(ABSTRACT)
    abstract_paragraph.paragraph_format.space_after = Pt(10)
    abstract_paragraph.paragraph_format.line_spacing = 1.16

    document.add_heading("1. Problem Definition", level=1)
    document.add_paragraph(
        "Quantum computing education and early-stage research often involve a fragmented workflow: users construct "
        "circuits in one environment, simulate them in another, inspect results separately, and assemble explanations "
        "or reports by hand. Many existing frameworks are capable and mature, yet their programming-first interfaces "
        "can make the first successful experiment difficult for learners and interdisciplinary users. Users also need "
        "clear distinctions between ideal simulation, noisy simulation, estimates, and execution on physical quantum "
        "hardware. QScope addresses this usability and continuity problem by bringing a local circuit-to-explanation "
        "workflow into one application, with technical evidence and limitations visible alongside results."
    )

    document.add_heading("2. Project Objectives", level=1)
    objectives = [
        "Provide an approachable starting point for learning and exploring quantum circuits.",
        "Let users create circuits visually, load common algorithms, and import OpenQASM programs.",
        "Run simulations locally on ordinary computers, with resource estimates and memory safeguards.",
        "Explain circuit behavior through measurement distributions, state amplitudes, phase, entanglement, and gate-by-gate traces.",
        "Support optimization, noise studies, parameter experiments, benchmarking, saved history, and report generation.",
        "Offer a grounded assistant that answers from QScope artifacts and communicates uncertainty or missing evidence.",
        "Keep simulation, hardware estimates, and real-hardware results explicitly distinguished and reproducible."
    ]
    for item in objectives:
        add_numbered(document, item)

    document.add_heading("3. Scope and Future Role", level=1)
    document.add_paragraph(
        "The current project includes a Python/NumPy quantum engine with statevector, density-matrix, and trajectory "
        "simulation; a local web interface; circuit editing and QASM import; execution and measurement; tracing and "
        "state comparison; analysis and optimization; noise and hardware-estimation tools; experiments, benchmarks, "
        "history, and reports; and an assistant grounded in attached project data."
    )
    document.add_paragraph(
        "Future development can make QScope a dependable personal quantum laboratory: a guided learning companion "
        "for beginners, a visual debugging and reproducibility environment for researchers, and a bridge to optional "
        "quantum hardware providers. Planned growth includes richer interactive algorithm lessons (including carefully "
        "scoped Shor demonstrations), named projects and comparisons, improved CPU/GPU backends where practical, "
        "desktop packaging, and reusable templates for exploring optimization, chemistry, and quantum machine-learning "
        "examples. These are future directions, not claims that every capability is implemented today."
    )

    document.add_heading("4. Proposed System", level=1)
    document.add_paragraph(
        "QScope is proposed as a local-first application in which a guided, chat-like interface leads into a shared "
        "circuit workspace. A user can ask a question, select a starter algorithm, create or import a circuit, run it "
        "through the Python engine, and inspect a visual account of what changed. Advanced controls remain available "
        "for detailed analysis and reproducible research. The Python API is the source of computed results; the user "
        "interface displays returned artifacts rather than inventing measurements."
    )
    architecture = document.add_table(rows=0, cols=2)
    architecture.alignment = WD_TABLE_ALIGNMENT.CENTER
    architecture.style = "Light Shading Accent 1"
    architecture_rows = [
        ("Layer", "Responsibility"),
        ("Guided interface", "Question-led home, circuit canvas, result views, assistant, and beginner/research detail levels."),
        ("Python API", "Validates circuit documents and provides HTTP/WebSocket access to execution and research operations."),
        ("Quantum engine", "NumPy-based statevector, density-matrix, and trajectory simulation with measurement and resource planning."),
        ("Research services", "Tracing, analysis, optimization, noise models, experiments, benchmarks, history, and exports."),
        ("Grounded assistant", "Builds explanations from selected circuits, simulations, traces, and stored artifacts; optional narration is constrained by computed evidence."),
    ]
    for row_index, row in enumerate(architecture_rows):
        cells = architecture.add_row().cells
        for col_index, value in enumerate(row):
            cells[col_index].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            set_cell_text(cells[col_index], value, bold=(row_index == 0 or col_index == 0), color="FFFFFF" if row_index == 0 else "243047")
            if row_index == 0:
                shade(cells[col_index], "087F8C")
    document.add_paragraph(
        "Typical flow: Ask or choose an example → Build/import → Plan safely → Run locally → Inspect state and trace → "
        "Analyze/optimize/experiment → Save, compare, or report."
    )

    document.add_heading("5. Existing Tools and How QScope Differs", level=1)
    document.add_paragraph(
        "Quantum software already includes powerful SDKs, local simulators, circuit visualizers, and educational "
        "experiences. QScope should therefore be understood as a complementary integration and usability project, "
        "not as a claim to replace these ecosystems or to be the only tool with any individual feature. The comparison "
        "below summarizes their documented emphases and QScope’s intended distinction."
    )
    comparison = document.add_table(rows=0, cols=3)
    comparison.alignment = WD_TABLE_ALIGNMENT.CENTER
    comparison.style = "Light Shading Accent 1"
    rows = [
        ("Existing tool", "Documented emphasis", "QScope’s intended distinction"),
        ("Qiskit", "Python quantum SDK for constructing circuits, transpiling them for target hardware, and visualizing circuits/results.", "QScope packages a guided local workflow around simulation, state tracing, analysis, reproducibility, and explanations for users who want one integrated learning/research surface."),
        ("Microsoft QDK", "Quantum development toolkit with local simulators, language integrations, and paths to Azure Quantum hardware.", "QScope emphasizes an offline-capable, NumPy-based workspace and makes its own trace, measurement, resource, and research artifacts central to the user journey."),
        ("PennyLane", "Cross-platform quantum programming focused on differentiable programming and quantum machine learning, with multiple device integrations.", "QScope’s center is the inspectable circuit lifecycle—build, simulate, trace, compare, optimize, benchmark, and report—rather than differentiable hybrid model training."),
        ("Quirk", "Interactive browser-based quantum circuit simulator oriented toward visual experimentation and learning.", "QScope aims to extend a visual first step into a local Python engine, gate-level debugging, measured performance, history, and research exports."),
    ]
    for row_index, row in enumerate(rows):
        cells = comparison.add_row().cells
        for col_index, value in enumerate(row):
            cells[col_index].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            set_cell_text(cells[col_index], value, bold=(row_index == 0 or col_index == 0), color="FFFFFF" if row_index == 0 else "243047", size=8.5)
            if row_index == 0:
                shade(cells[col_index], "5046A5")

    document.add_heading("6. Key Differentiators", level=1)
    for item in [
        "One continuous path from a plain-language question to a circuit, execution, explanation, and research artifact.",
        "Gate-by-gate tracing and state differences presented alongside circuit and measurement views.",
        "Local-first operation with explicit resource planning and reproducible run metadata.",
        "A grounded assistant designed to explain the user’s actual circuit and results rather than substitute for the simulator.",
        "Progressive disclosure: a simple guided experience first, with advanced controls available when needed.",
        "Clear provenance and honest labels separating local simulation, noisy models, hardware estimates, and real hardware."
    ]:
        add_bullet(document, item)

    document.add_heading("References", level=1)
    sources = [
        ("Qiskit documentation — Visualize circuits", "https://docs.quantum.ibm.com/guides/visualize-circuits"),
        ("Qiskit documentation — Introduction to transpilation", "https://docs.quantum.ibm.com/guides/transpile"),
        ("Microsoft Learn — Overview of quantum simulators in the QDK", "https://learn.microsoft.com/en-us/azure/quantum/simulators-overview-qdk"),
        ("Microsoft Learn — QDK overview", "https://learn.microsoft.com/en-us/azure/quantum/qdk-main-overview"),
        ("PennyLane documentation", "https://docs.pennylane.ai/en/stable/"),
        ("Quirk — open-source quantum circuit simulator", "https://github.com/Strilanc/Quirk"),
        ("QScope project README and implementation", "README.md (project repository)"),
    ]
    for label, url in sources:
        paragraph = document.add_paragraph(style="List Bullet")
        paragraph.paragraph_format.space_after = Pt(3)
        if url.startswith("https://"):
            add_hyperlink(paragraph, label, url)
        else:
            paragraph.add_run(f"{label} — {url}")
    note = document.add_paragraph(
        "Comparison note: descriptions reflect the linked primary documentation consulted on 12 October 2026. "
        "Feature sets evolve; the comparison is deliberately focused on product emphasis, not a complete feature audit."
    )
    note.paragraph_format.space_before = Pt(5)
    for run in note.runs:
        run.italic = True
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(100, 110, 125)

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer_run = footer.add_run("QScope · Project proposal")
    footer_run.font.size = Pt(8)
    footer_run.font.color.rgb = RGBColor(100, 110, 125)

    document.core_properties.title = "QScope Project Proposal"
    document.core_properties.subject = "Abstract, problem definition, objectives, scope, proposed system, and comparison"
    document.core_properties.author = "QScope Project"
    document.save(OUTPUT)
    print(f"Created {OUTPUT}")
    print(f"Abstract word count: {word_count}")


if __name__ == "__main__":
    main()
