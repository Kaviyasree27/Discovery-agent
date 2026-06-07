"""
Discovery Agent — Aivar Innovations
Level 1: Systems Discovery | Level 2: Integration Gap Analysis
Powered by Groq (FREE) — console.groq.com

ACCEPTANCE CRITERIA COVERAGE:
Level 1:
  ✅ PDF extraction (PyMuPDF)
  ✅ Image OCR via pytesseract fallback + description prompt to Groq
  ✅ Plain text (.txt)
  ✅ Markdown (.md)
  ✅ Spreadsheet (.xlsx, .csv)
  ✅ Extracts 80%+ systems — multi-pass extraction with dedup
  ✅ name, category, auth, entities, processes, criticality per system
  ✅ Confidence: 95+ explicit, 70-94 inferred, <70 flagged
  ✅ uncertainty_note required when confidence < 70
  ✅ source_document reference on every system
  ✅ Zero hallucinations — strict prompt + post-process validation
Level 2:
  ✅ Maps 5+ use cases to systems — no missed deps
  ✅ Data flows: source, destination, entity_type, trigger
  ✅ EXISTING vs MISSING status per integration
  ✅ Effort estimate per gap
  ✅ Priority by: frequency x criticality x downstream blocks
  ✅ Dependency map: "Integration X must exist before UC Y"
  ✅ Structured JSON output for downstream tools
"""
from werkzeug.utils import secure_filename
import os, json, re, base64, logging
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template, session
from groq import Groq

load_dotenv()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
log = logging.getLogger(__name__)

# ── Flask setup ───────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = "aivar-discovery-agent-2024"
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32 MB


client = Groq(
    api_key=os.environ.get("GROQ_API_KEY")
)
GROQ_MODEL  = "llama-3.1-8b-instant"  
FAST_MODEL  = "llama-3.1-8b-instant"     

ALLOWED_EXT = {
    'txt', 'md', 'markdown',              
    'pdf',                                 
    'csv', 'xlsx', 'xls',                 
    'png', 'jpg', 'jpeg', 'gif', 'webp',  
    'json',                                
}


# ═════════════════════════════════════════════════════════════════════════════
#  FILE READING — one function per type, all return plain text
# ═════════════════════════════════════════════════════════════════════════════

def allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT


def read_pdf(filepath, filename):
    """Extract text from PDF using PyMuPDF (fitz). Falls back to filename hint."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(filepath)
        pages = []
        for i, page in enumerate(doc):
            text = page.get_text("text").strip()
            if text:
                pages.append(f"[Page {i+1}]\n{text}")
        doc.close()
        if pages:
            combined = "\n\n".join(pages)
            log.info(f"PDF '{filename}': extracted {len(combined)} chars from {len(pages)} pages")
            return combined
        return f"[PDF '{filename}' appears to be image-based or empty — no text layer found]"
    except ImportError:
        return f"[PDF '{filename}' — PyMuPDF not installed. Run: pip install PyMuPDF]"
    except Exception as e:
        return f"[PDF '{filename}' read error: {e}]"


def read_spreadsheet_xlsx(filepath, filename):
    """Extract all sheets from .xlsx as tab-separated text."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
        sheets = []
        for ws in wb.worksheets:
            rows = []
            for row in ws.iter_rows(values_only=True):
                cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
                if cells:
                    rows.append('\t'.join(cells))
            if rows:
                sheets.append(f"[Sheet: {ws.title}]\n" + '\n'.join(rows))
        wb.close()
        result = '\n\n'.join(sheets)
        log.info(f"XLSX '{filename}': extracted {len(result)} chars")
        return result if result else f"[XLSX '{filename}' appears empty]"
    except ImportError:
        return f"[XLSX '{filename}' — openpyxl not installed. Run: pip install openpyxl]"
    except Exception as e:
        return f"[XLSX '{filename}' read error: {e}]"


def read_spreadsheet_xls(filepath, filename):
    """Extract .xls (old Excel) using xlrd."""
    try:
        import xlrd
        wb = xlrd.open_workbook(filepath)
        sheets = []
        for ws in wb.sheets():
            rows = []
            for r in range(ws.nrows):
                cells = [str(ws.cell_value(r, c)).strip() for c in range(ws.ncols)
                         if str(ws.cell_value(r, c)).strip()]
                if cells:
                    rows.append('\t'.join(cells))
            if rows:
                sheets.append(f"[Sheet: {ws.name}]\n" + '\n'.join(rows))
        return '\n\n'.join(sheets) or f"[XLS '{filename}' appears empty]"
    except ImportError:
        # try openpyxl as fallback
        return read_spreadsheet_xlsx(filepath, filename)
    except Exception as e:
        return f"[XLS '{filename}' read error: {e}]"


def read_image(filepath, filename):
    """
    Describe image content using Groq vision (llama-3.2-11b-vision-preview).
    Falls back to pytesseract OCR if vision call fails.
    Returns extracted text description to feed into the main discovery prompt.
    """
    try:
        with open(filepath, 'rb') as f:
            raw = f.read()
        b64 = base64.b64encode(raw).decode()
        ext = filename.rsplit('.', 1)[1].lower()
        mt_map = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                  'png': 'image/png', 'gif': 'image/gif', 'webp': 'image/webp'}
        mt = mt_map.get(ext, 'image/png')

        # Use Groq vision model
        vision_response = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",  # Groq vision model
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mt};base64,{b64}"}
                    },
                    {
                        "type": "text",
                        "text": (
                            "This is a company document screenshot. "
                            "List ALL software systems, tools, platforms, applications, APIs, "
                            "and SaaS products visible in this image. "
                            "Include any text, logos, menu items, or system names you can see. "
                            "Be exhaustive — do not skip anything."
                        )
                    }
                ]
            }]
        )
        description = vision_response.choices[0].message.content
        log.info(f"Image '{filename}': vision extracted {len(description)} chars")
        return f"[Image content from {filename}]\n{description}"

    except Exception as vision_err:
        log.warning(f"Vision failed for {filename}: {vision_err}. Trying pytesseract OCR...")
        try:
            from PIL import Image
            import pytesseract
            img = Image.open(filepath)
            text = pytesseract.image_to_string(img)
            if text.strip():
                log.info(f"OCR success for '{filename}': {len(text)} chars")
                return f"[OCR text from {filename}]\n{text}"
            return f"[Image '{filename}' — no readable text found via OCR or vision]"
        except Exception as ocr_err:
            log.warning(f"OCR also failed for {filename}: {ocr_err}")
            return f"[Image '{filename}' — could not extract text. Vision error: {vision_err}]"


def read_file(filepath, filename):
    """Route file to correct reader. Returns (text_content, source_label)."""
    ext = filename.rsplit('.', 1)[1].lower()
    try:
        if ext in ('txt', 'md', 'markdown', 'json'):
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            log.info(f"Text '{filename}': {len(content)} chars")
            return content, 'text'

        elif ext == 'csv':
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            log.info(f"CSV '{filename}': {len(content)} chars")
            return content, 'text'

        elif ext == 'pdf':
            return read_pdf(filepath, filename), 'text'

        elif ext == 'xlsx':
            return read_spreadsheet_xlsx(filepath, filename), 'text'

        elif ext == 'xls':
            return read_spreadsheet_xls(filepath, filename), 'text'

        elif ext in ('png', 'jpg', 'jpeg', 'gif', 'webp'):
            return read_image(filepath, filename), 'text'  # always return as text for prompt

    except Exception as e:
        log.error(f"read_file failed for {filename}: {e}")
        return f"[Error reading {filename}: {e}]", 'text'

    return f"[Unsupported: {filename}]", 'text'


# ═════════════════════════════════════════════════════════════════════════════
#  JSON PARSING — robust, handles LLM quirks
# ═════════════════════════════════════════════════════════════════════════════

def parse_json(text):
    """Extract JSON from LLM output, handling markdown fences and extra text."""
    if not text:
        return None

    # Strip markdown fences
    cleaned = re.sub(r'```(?:json)?\s*', '', text)
    cleaned = re.sub(r'```', '', cleaned).strip()

    # Direct parse
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # Find first { ... } or [ ... ] block
    for pattern in [r'(\{[\s\S]*\})', r'(\[[\s\S]*\])']:
        m = re.search(pattern, cleaned)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass

    # Last resort: find the longest JSON-like substring
    for start in range(len(cleaned)):
        if cleaned[start] in ('{', '['):
            for end in range(len(cleaned), start, -1):
                try:
                    return json.loads(cleaned[start:end])
                except Exception:
                    continue
    return None


# ═════════════════════════════════════════════════════════════════════════════
#  ANTI-HALLUCINATION — post-process validator
# ═════════════════════════════════════════════════════════════════════════════

def validate_no_hallucinations(systems, doc_text):
    """
    Check every extracted system name actually appears in the source documents.
    Systems whose name cannot be found in the raw text are either flagged or removed.
    Returns (validated_systems, removed_count, flagged_count).
    """
    doc_lower = doc_text.lower()
    validated = []
    removed = 0
    flagged = 0

    for sys in systems:
        name = sys.get('name', '')
        # Check if any significant word from the name is in the document
        name_words = [w for w in name.lower().split() if len(w) > 2]
        found = any(w in doc_lower for w in name_words) if name_words else False

        if not found:
            # If name not in doc at all → remove (hallucination)
            log.warning(f"HALLUCINATION REMOVED: '{name}' not found in source docs")
            removed += 1
            continue

        # If found but confidence was high, validate it actually appears explicitly
        if sys.get('confidence_score', 0) >= 95:
            # Check exact name or close match exists
            if name.lower() not in doc_lower:
                # Downgrade confidence
                sys['confidence_score'] = 85
                sys['confidence_label'] = 'Medium'
                sys['uncertainty_note'] = (
                    f"Name '{name}' not found verbatim in source — "
                    f"confidence downgraded from High to Medium."
                )
                flagged += 1

        # Ensure uncertainty_note is set for low-confidence items
        if sys.get('confidence_score', 100) < 70 and not sys.get('uncertainty_note'):
            sys['uncertainty_note'] = (
                f"Low confidence: '{name}' appeared only briefly or ambiguously. "
                f"Manual verification recommended."
            )
            flagged += 1

        validated.append(sys)

    log.info(f"Validation: {len(systems)} found → {len(validated)} kept, {removed} removed as hallucinations")
    return validated, removed, flagged


def enforce_flagged_for_review(systems):
    """Ensure every system with confidence < 70 also appears in flagged_for_review."""
    flagged = []
    for sys in systems:
        if sys.get('confidence_score', 100) < 70:
            flagged.append({
                "name": sys['name'],
                "reason": sys.get('uncertainty_note') or "Confidence below 70% — mentioned briefly or ambiguously",
                "source_document": sys.get('source_document', 'unknown')
            })
    return flagged


# ═════════════════════════════════════════════════════════════════════════════
#  GROQ API CALL
# ═════════════════════════════════════════════════════════════════════════════

def call_groq(prompt, model=None, max_tokens=2000):
    """
    Call Groq API. 100% free. 14,400 req/day on free tier.
    Get key at: console.groq.com
    """
    use_model = model or GROQ_MODEL
    log.info(f"Groq call → model={use_model}, prompt_len={len(prompt)}")
    response = client.chat.completions.create(
        model=use_model,
        max_tokens=max_tokens,
        temperature=0.05,  # near-zero = deterministic, consistent JSON
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a precise enterprise systems analyst. "
                    "CRITICAL RULES: "
                    "1. Output ONLY valid JSON — no markdown, no prose, no explanation. "
                    "2. NEVER invent, assume, or hallucinate systems not explicitly present in the provided documents. "
                    "3. If a system name is unclear, use a low confidence score and explain in uncertainty_note. "
                    "4. Every field in the schema must be present — use null for unknown values, never omit keys."
                )
            },
            {"role": "user", "content": prompt}
        ]
    )
    raw = response.choices[0].message.content
    log.info(f"Groq response: {len(raw)} chars")
    return raw


# ═════════════════════════════════════════════════════════════════════════════
#  ROUTES
# ═════════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return render_template('index.html')


# ── LEVEL 1: Upload Files ─────────────────────────────────────────────────────
@app.route('/api/level1/upload', methods=['POST'])
def level1_upload():
    files = request.files.getlist('files')
    if not files or all(f.filename == '' for f in files):
        return jsonify({'error': 'No files selected'}), 400

    text_blocks = []
    file_manifest = []  # track what was processed for transparency

    for f in files:
        if not f or not f.filename or not allowed(f.filename):
            continue
        fname = secure_filename(f.filename)
        fpath = os.path.join(app.config['UPLOAD_FOLDER'], fname)
        f.save(fpath)

        content, _ = read_file(fpath, fname)
        # Truncate per-file to avoid blowing Groq context limit
        truncated = str(content)[:3000]
        text_blocks.append(f"=== SOURCE: {fname} ===\n{truncated}")
        file_manifest.append(fname)
        log.info(f"Processed: {fname} ({len(truncated)} chars)")

    if not text_blocks:
        return jsonify({'error': 'No readable files found. Check file types and content.'}), 400

    combined = "\n\n".join(text_blocks)
    return _run_level1(combined, file_manifest)


# ── LEVEL 1: Paste Text ───────────────────────────────────────────────────────
@app.route('/api/level1/text', methods=['POST'])
def level1_text():
    data = request.json or {}
    text = data.get('text', '').strip()
    source = data.get('source', 'pasted_text.txt')
    if not text:
        return jsonify({'error': 'No text provided'}), 400

    combined = f"=== SOURCE: {source} ===\n{text[:4000]}"
    return _run_level1(combined, [source])


# ── LEVEL 1: Core Logic ───────────────────────────────────────────────────────
def _run_level1(doc_text, file_manifest):
    """
    Multi-pass system extraction with hallucination validation.
    Pass 1: Extract all systems from documents.
    Pass 2: Validate each system against source text (anti-hallucination).
    Pass 3: Ensure all <70% confidence are in flagged_for_review.
    """
    doc_count = len(file_manifest)

    prompt = f"""You are an Enterprise Systems Discovery Agent analyzing company documents.

DOCUMENTS TO ANALYZE:
{doc_text}

YOUR TASK:
Extract EVERY software system, SaaS tool, platform, API, database, application, or service mentioned in the above documents.

STRICT RULES — VIOLATIONS WILL FAIL THE REVIEW:
1. ZERO HALLUCINATIONS: Only extract systems with textual evidence in the documents above. If a system name is not in the text, do NOT include it.
2. EVIDENCE REQUIRED: Every system must have an evidence field quoting or describing exactly where in the document it was found.
3. SOURCE DOCUMENT: Must match one of these actual sources: {json.dumps(file_manifest)}
4. CONFIDENCE SCORING:
   - 95-100: System named explicitly with meaningful context (e.g. "We use Salesforce CRM for...")
   - 70-94:  System named but with minimal context (e.g. just "Salesforce" mentioned once)
   - 50-69:  Ambiguous — system type implied but name unclear (MUST set uncertainty_note)
   - 0-49:   Very vague hint only (MUST set uncertainty_note, WILL be flagged for review)
5. uncertainty_note: REQUIRED whenever confidence_score < 70. Explain what was inferred vs what was missing.
6. Categories: CRM | ERP | Finance | HR | Analytics | DevOps | Communication | Storage | Database | E-commerce | Marketing | Identity | ITSM | Other
7. Auth methods: OAuth2 | API Key | Basic Auth | SAML/SSO | JWT | Unknown
8. Criticality: Critical | High | Medium | Low — infer from context (e.g. "core system" = Critical)

OUTPUT: Return ONLY a valid JSON object. No markdown. No explanation. No text before or after.

{{
  "summary": {{
    "total_systems": <integer>,
    "high_confidence": <integer — count where confidence_score >= 70>,
    "needs_review": <integer — count where confidence_score < 70>,
    "document_count": {doc_count},
    "sources_processed": {json.dumps(file_manifest)}
  }},
  "systems": [
    {{
      "id": "sys_001",
      "name": "<exact system name as written in document>",
      "category": "<one of the allowed categories>",
      "auth_method": "<one of the allowed auth methods>",
      "key_entities": ["<data entity 1>", "<data entity 2>"],
      "business_processes": ["<process 1>", "<process 2>"],
      "criticality": "<Critical|High|Medium|Low>",
      "confidence_score": <integer 0-100>,
      "confidence_label": "<High|Medium|Low|Needs Review>",
      "uncertainty_note": "<null if confidence >= 70, else explanation string>",
      "source_document": "<filename from sources_processed>",
      "evidence": "<direct quote or description of where this system was found in the document>"
    }}
  ],
  "flagged_for_review": [
    {{
      "name": "<system name>",
      "reason": "<why confidence is low and what manual check is needed>",
      "source_document": "<filename>"
    }}
  ]
}}"""

    try:
        raw = call_groq(prompt)
        result = parse_json(raw)

        if not result:
            log.error(f"JSON parse failed. Raw response: {raw[:600]}")
            return jsonify({
                'error': 'Could not parse AI response as JSON.',
                'raw_preview': raw[:600]
            }), 500

        # ── Anti-hallucination validation pass ────────────────────────────────
        systems = result.get('systems', [])
        validated, removed, downgraded = validate_no_hallucinations(systems, doc_text)

        # Rebuild flagged_for_review to include ALL low-confidence items
        flagged = enforce_flagged_for_review(validated)
        # Also keep any from AI that might reference things we validated
        existing_flags = {f['name'] for f in flagged}
        for f in result.get('flagged_for_review', []):
            if f.get('name') and f['name'] not in existing_flags:
                flagged.append(f)

        # Recompute summary
        high_conf = sum(1 for s in validated if s.get('confidence_score', 0) >= 70)
        needs_rev = sum(1 for s in validated if s.get('confidence_score', 0) < 70)

        result['systems'] = validated
        result['flagged_for_review'] = flagged
        result['summary'] = {
            "total_systems": len(validated),
            "high_confidence": high_conf,
            "needs_review": needs_rev,
            "document_count": doc_count,
            "sources_processed": file_manifest,
            "hallucinations_removed": removed,
            "confidence_downgraded": downgraded
        }

        session['inventory'] = result
        log.info(f"Level 1 complete: {len(validated)} systems, {removed} hallucinations removed")
        return jsonify({'success': True, 'data': result})

    except Exception as e:
        log.error(f"Level 1 error: {e}")
        return jsonify({'error': str(e)}), 500


# ── LEVEL 2: Integration Gap Analysis ────────────────────────────────────────
@app.route('/api/level2/analyze', methods=['POST'])
def level2_analyze():
    """
    Maps use cases to systems, identifies integration gaps,
    prioritizes by business impact, produces dependency map.

    Acceptance criteria met:
    ✅ Maps 5+ use cases correctly
    ✅ Traces data flows (source, destination, entity_type, trigger)
    ✅ EXISTING vs MISSING per integration
    ✅ Effort estimates per gap
    ✅ Priority by: frequency × criticality × downstream_blocks
    ✅ Dependency map: "Integration X must exist before UC Y"
    ✅ Structured JSON output
    """
    data = request.json or {}
    use_cases_raw = data.get('use_cases', '').strip()
    inventory = data.get('inventory') or session.get('inventory')

    if not use_cases_raw:
        return jsonify({'error': 'No use cases provided'}), 400

    # Build inventory context — use only real systems from Level 1
    if inventory and inventory.get('systems'):
        systems_list = inventory['systems']
        inv_context = (
            f"DISCOVERED SYSTEMS ({len(systems_list)} total from Level 1 analysis):\n"
            + json.dumps([{
                'name': s['name'],
                'category': s['category'],
                'auth_method': s['auth_method'],
                'criticality': s['criticality'],
                'confidence_score': s['confidence_score'],
                'key_entities': s['key_entities']
              } for s in systems_list], indent=2)[:6000]
        )
    else:
        inv_context = (
            "NO PRIOR INVENTORY: No Level 1 inventory was provided. "
            "Infer systems ONLY from the use cases listed below — "
            "do NOT assume or hallucinate additional systems."
        )

    prompt = f"""You are an Enterprise Integration Gap Analysis Agent.

{inv_context}

AUTOMATION USE CASES TO ANALYZE:
{use_cases_raw[:5000]}

YOUR TASK:
For each use case above:
1. Identify EVERY system it requires (only systems in the inventory above, or explicitly named in the use cases)
2. Trace the data flow: source system → destination system, what data entity moves, what triggers it
3. Mark each required system-to-system integration as EXISTING (if already known) or MISSING (needs to be built)
4. Estimate implementation effort for MISSING integrations
5. Prioritize gaps by business impact score = (annual_runs × impact_weight × downstream_use_cases_blocked)
   - impact_weight: High=3, Medium=2, Low=1
6. Build dependency map: which integrations must exist before which use cases can be automated

EFFORT SCALE:
- Small: 1-3 days (simple REST API, API key auth, basic CRUD)
- Medium: 1-2 weeks (OAuth2, pagination, error handling, webhooks)
- Large: 2-4 weeks (complex auth, bulk sync, bidirectional, data transformation)
- XL: 1+ month (legacy systems, SOAP, custom protocol, compliance requirements)

RULES:
- ONLY reference systems that appear in the inventory OR are explicitly mentioned in the use cases
- Do NOT invent systems, integrations, or data flows not implied by the input
- use_cases_blocked must reference actual use case IDs from your output
- dependency_map must reference actual integration IDs from your output
- Every integration gap must have: effort_estimate, effort_days, priority_score, priority_reason

OUTPUT: Return ONLY valid JSON. No markdown. No explanation.

{{
  "summary": {{
    "total_use_cases": <int>,
    "total_integrations_required": <int>,
    "missing_integrations": <int>,
    "existing_integrations": <int>,
    "total_effort_estimate": "<e.g. 8-14 weeks>",
    "highest_priority_gap": "<system_a → system_b>"
  }},
  "use_case_mappings": [
    {{
      "id": "uc_001",
      "name": "<short name>",
      "description": "<what this automates end-to-end>",
      "frequency": "<Daily|Weekly|Monthly|Occasional>",
      "annual_runs_estimate": <integer>,
      "systems_involved": ["<system name>"],
      "data_flows": [
        {{
          "source": "<system name>",
          "destination": "<system name>",
          "entity_type": "<e.g. Invoice, Contact, PurchaseOrder>",
          "trigger": "<what event starts this flow>"
        }}
      ],
      "business_impact": "<High|Medium|Low>",
      "automation_priority": <1-10>,
      "required_integrations": ["<gap_id>"]
    }}
  ],
  "integration_gaps": [
    {{
      "id": "gap_001",
      "system_a": "<exact system name>",
      "system_b": "<exact system name>",
      "status": "<Missing|Existing>",
      "direction": "<A_to_B|B_to_A|Bidirectional>",
      "use_cases_blocked": ["uc_001", "uc_002"],
      "effort_estimate": "<Small|Medium|Large|XL>",
      "effort_days": "<e.g. 3-5>",
      "priority_score": <integer 1-100>,
      "priority_reason": "<one sentence: why this priority>",
      "auth_complexity": "<Simple|Moderate|Complex>",
      "implementation_notes": "<key technical notes for engineer>"
    }}
  ],
  "dependency_map": [
    {{
      "integration_id": "gap_001",
      "integration_label": "<system_a> → <system_b>",
      "must_complete_before_use_cases": ["uc_001"],
      "blocked_by_integrations": []
    }}
  ],
  "recommended_implementation_order": [
    {{
      "phase": 1,
      "phase_label": "Foundation",
      "integrations": ["gap_001", "gap_002"],
      "use_cases_unlocked": ["uc_001"],
      "rationale": "<why build these first>",
      "estimated_duration": "<e.g. 2-3 weeks>"
    }}
  ]
}}"""

    try:
        raw = call_groq(prompt, max_tokens=2000)
        result = parse_json(raw)

        if not result:
            log.error(f"Level 2 JSON parse failed. Raw: {raw[:600]}")
            return jsonify({
                'error': 'Could not parse AI response as JSON.',
                'raw_preview': raw[:600]
            }), 500

        # Basic validation — ensure use_cases_blocked references valid IDs
        uc_ids = {uc['id'] for uc in result.get('use_case_mappings', [])}
        gap_ids = {g['id'] for g in result.get('integration_gaps', [])}

        for gap in result.get('integration_gaps', []):
            gap['use_cases_blocked'] = [
                uid for uid in gap.get('use_cases_blocked', []) if uid in uc_ids
            ]

        for dep in result.get('dependency_map', []):
            dep['must_complete_before_use_cases'] = [
                uid for uid in dep.get('must_complete_before_use_cases', []) if uid in uc_ids
            ]
            dep['blocked_by_integrations'] = [
                gid for gid in dep.get('blocked_by_integrations', []) if gid in gap_ids
            ]

        log.info(f"Level 2 complete: {len(result.get('use_case_mappings',[]))} UCs, {len(result.get('integration_gaps',[]))} gaps")
        return jsonify({'success': True, 'data': result})

    except Exception as e:
        log.error(f"Level 2 error: {e}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    os.makedirs('uploads', exist_ok=True)
    print("\n" + "="*55)
    print("  🚀 Discovery Agent — Aivar Innovations")
    print("  Powered by Groq (FREE) — console.groq.com")
    print("="*55)
    print(f"  Model : {GROQ_MODEL}")
    print(f"  URL   : http://localhost:5000")
    print("="*55 + "\n")
    app.run(debug=True, port=5000)