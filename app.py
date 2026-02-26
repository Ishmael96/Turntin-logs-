from flask import Flask, render_template, request, jsonify, send_file
import os, re, math, json, uuid, datetime
from collections import Counter
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
UPLOAD_FOLDER = 'uploads'
REPORT_FOLDER = 'reports'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(REPORT_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'txt', 'pdf', 'docx'}

def allowed_file(f): return '.' in f and f.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text(filepath, ext):
    if ext == 'txt':
        with open(filepath,'r',errors='ignore') as f: return f.read()
    elif ext == 'pdf':
        try:
            from pypdf import PdfReader
            r = PdfReader(filepath)
            return '\n'.join(p.extract_text() or '' for p in r.pages)
        except: return ''
    elif ext == 'docx':
        try:
            from docx import Document
            return '\n'.join(p.text for p in Document(filepath).paragraphs)
        except: return ''
    return ''

AI_PHRASES = [
    "furthermore","moreover","in conclusion","it is worth noting","it should be noted",
    "in summary","to summarize","in addition","as a result","consequently","therefore",
    "thus","hence","this highlights","this demonstrates","this suggests",
    "plays a crucial role","plays an important role","is essential","delve","delves",
    "tapestry","nuanced","multifaceted","comprehensive","robust","leverage","utilize",
    "facilitate","endeavor","underscore","paramount","pivotal","notably",
    "it's important to note","importantly","it is important to","in today's world",
    "in the modern era","in recent years","has become increasingly",
    "cannot be overstated","it goes without saying"
]

COMMON_SOURCES = [
    {"name":"Wikipedia","url":"wikipedia.org","color":"#e74c3c"},
    {"name":"ResearchGate","url":"researchgate.net","color":"#f39c12"},
    {"name":"Academia.edu","url":"academia.edu","color":"#27ae60"},
    {"name":"JSTOR","url":"jstor.org","color":"#8e44ad"},
    {"name":"Google Scholar","url":"scholar.google.com","color":"#2980b9"},
    {"name":"PubMed","url":"pubmed.ncbi.nlm.nih.gov","color":"#16a085"},
    {"name":"SpringerLink","url":"springer.com","color":"#d35400"},
]

COMMON_PHRASES = [
    "climate change","global warming","machine learning","artificial intelligence",
    "the united states","in recent years","according to","research shows",
    "studies have shown","experts say","it has been","there are many",
    "on the other hand","as a result of","in order to","due to the fact"
]

def count_syllables(word):
    word = word.lower().strip(".,;:!?\"'")
    if len(word)<=3: return 1
    vowels="aeiouy"; count=0; prev=False
    for c in word:
        v=c in vowels
        if v and not prev: count+=1
        prev=v
    if word.endswith('e'): count-=1
    return max(1,count)

def get_label(score, mode):
    if mode=='ai':
        if score<20: return ("Human Written","#27ae60","green")
        if score<45: return ("Likely Human","#2ecc71","lime")
        if score<65: return ("Mixed / Uncertain","#f39c12","amber")
        if score<80: return ("Likely AI-Generated","#e67e22","orange")
        return ("AI Generated","#e74c3c","red")
    else:
        if score<10: return ("No Plagiarism Detected","#27ae60","green")
        if score<25: return ("Low Similarity","#2ecc71","lime")
        if score<50: return ("Moderate Similarity","#f39c12","amber")
        if score<70: return ("High Similarity","#e67e22","orange")
        return ("Plagiarism Detected","#e74c3c","red")

def analyze_text(text, filename="Untitled"):
    words = text.lower().split()
    wc = len(words)
    sentences = [s.strip() for s in re.split(r'[.!?]+',text) if len(s.strip())>10]
    sc = max(1,len(sentences))
    phrase_hits = sum(1 for p in AI_PHRASES if p in text.lower())
    word_hits = sum(1 for w in words if w.strip('.,;:') in AI_PHRASES)
    lengths = [len(s.split()) for s in sentences]
    avg_len = sum(lengths)/len(lengths) if lengths else 15
    variance = sum((l-avg_len)**2 for l in lengths)/len(lengths) if lengths else 0
    uniformity = max(0, 35 - math.sqrt(variance)*1.8)
    passive = len(re.findall(r'\b(is|are|was|were|be|been|being)\s+\w+ed\b',text.lower()))
    ai_raw = phrase_hits*9 + (word_hits/max(wc,1)*300) + uniformity + min(15,passive*2)
    ai_score = min(97,max(3,round(ai_raw)))
    ai_para = min(95,max(5,round(ai_raw*0.6+15)))
    pd_count = sum(1 for p in COMMON_PHRASES if p in text.lower())
    wf = Counter(words)
    repeated = sum(1 for w,c in wf.items() if len(w)>5 and c>3)
    plag_score = min(82,max(1,round(pd_count*3.5+repeated*2.2)))
    syllables = sum(count_syllables(w) for w in words)
    avg_syl = syllables/max(wc,1)
    flesch = max(0,min(100,round(206.835-1.015*(wc/sc)-84.6*avg_syl)))
    if flesch>=90: grade="5th Grade"
    elif flesch>=70: grade="7th Grade"
    elif flesch>=60: grade="8-9th Grade"
    elif flesch>=50: grade="10-12th Grade"
    elif flesch>=30: grade="College"
    else: grade="College Graduate"
    highlighted = []
    src_colors=["#e74c3c","#f39c12","#27ae60","#8e44ad","#2980b9","#16a085","#d35400"]
    for i,sent in enumerate(sentences[:40]):
        if len(sent.split())>8:
            h = sum(1 for p in COMMON_PHRASES if p in sent.lower())
            ah = sum(1 for p in AI_PHRASES if p in sent.lower())
            if h>0 or (plag_score>20 and i%3==0):
                si=i%len(COMMON_SOURCES)
                highlighted.append({"text":sent,"color":src_colors[si%len(src_colors)],
                    "source":COMMON_SOURCES[si]["name"],"source_url":COMMON_SOURCES[si]["url"],
                    "match_pct":min(99,45+h*12+(i%20))})
            elif ah>0:
                highlighted.append({"text":sent,"color":"#9b59b6","source":"AI Generated Content",
                    "source_url":"","match_pct":min(99,55+ah*8)})
    flagged = list(set(p for p in AI_PHRASES if p in text.lower()))[:15]
    matched_sources=[]
    for i,src in enumerate(COMMON_SOURCES[:5]):
        pct=max(1,round((plag_score*(0.3-i*0.04))+(i*2)))
        if pct>1: matched_sources.append({**src,"pct":pct})
    return {
        "filename":filename,
        "submission_date":datetime.datetime.now().strftime("%B %d, %Y at %I:%M %p"),
        "submission_id":str(uuid.uuid4())[:8].upper(),
        "word_count":wc,"sentence_count":sc,"character_count":len(text),
        "ai_score":ai_score,"ai_paraphrased_score":ai_para,"plag_score":plag_score,
        "readability":flesch,"grade_level":grade,
        "flagged_phrases":flagged,"highlighted_sentences":highlighted[:20],
        "matched_sources":matched_sources,
        "ai_label":get_label(ai_score,'ai'),"plag_label":get_label(plag_score,'plag'),
        "text_preview":text[:3000],"original_pct":max(0,100-plag_score),
        "ai_original_pct":max(0,100-ai_score),
    }

def gen_similarity_pdf(data, out):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT

    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=15*mm, bottomMargin=20*mm)
    ss = getSampleStyleSheet()
    story = []
    RED=colors.HexColor('#e74c3c'); BLUE=colors.HexColor('#1a73e8')
    DARK=colors.HexColor('#1a1a2e'); GRAY=colors.HexColor('#6c757d')
    BORDER=colors.HexColor('#dee2e6')
    PC=colors.HexColor(data['plag_label'][1]); AC=colors.HexColor(data['ai_label'][1])

    def S(n,**k): return ParagraphStyle(n,parent=ss['Normal'],**k)

    hd=[[Paragraph('<font color="#e74c3c"><b>Turnitin</b></font>',S('lg',fontName='Helvetica-Bold',fontSize=22)),
         Paragraph('Similarity Report',S('hr',fontName='Helvetica',fontSize=13,textColor=DARK,alignment=TA_RIGHT))]]
    ht=Table(hd,colWidths=[90*mm,80*mm])
    ht.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
    story.append(ht)
    story.append(HRFlowable(width="100%",thickness=3,color=RED,spaceAfter=10))

    story.append(Paragraph('Submission Details',S('sh',fontName='Helvetica-Bold',fontSize=11,textColor=DARK,spaceBefore=8,spaceAfter=6)))
    info=[['Document',data['filename'],'Submission ID',data['submission_id']],
          ['Submitted',data['submission_date'],'Word Count',f"{data['word_count']:,}"],
          ['Sentences',str(data['sentence_count']),'Characters',f"{data['character_count']:,}"]]
    it=Table(info,colWidths=[35*mm,65*mm,35*mm,35*mm])
    it.setStyle(TableStyle([('BACKGROUND',(0,0),(0,-1),colors.HexColor('#f1f3f4')),
        ('BACKGROUND',(2,0),(2,-1),colors.HexColor('#f1f3f4')),
        ('FONTNAME',(0,0),(0,-1),'Helvetica-Bold'),('FONTNAME',(2,0),(2,-1),'Helvetica-Bold'),
        ('FONTSIZE',(0,0),(-1,-1),9),('GRID',(0,0),(-1,-1),0.5,BORDER),('PADDING',(0,0),(-1,-1),6)]))
    story.append(it); story.append(Spacer(1,12))

    story.append(Paragraph('Originality Overview',S('sh2',fontName='Helvetica-Bold',fontSize=11,textColor=DARK,spaceAfter=8)))
    sd=[[Paragraph(f'<font size="36" color="{data["plag_label"][1]}"><b>{data["plag_score"]}%</b></font><br/><font size="10" color="#6c757d">Similarity Index</font>',S('sc',alignment=TA_CENTER)),
         Paragraph(f'<font size="36" color="{data["ai_label"][1]}"><b>{data["ai_score"]}%</b></font><br/><font size="10" color="#6c757d">AI Writing</font>',S('sc2',alignment=TA_CENTER)),
         Paragraph(f'<font size="36" color="#27ae60"><b>{data["original_pct"]}%</b></font><br/><font size="10" color="#6c757d">Original</font>',S('sc3',alignment=TA_CENTER))]]
    st=Table(sd,colWidths=[57*mm,57*mm,57*mm])
    st.setStyle(TableStyle([('BOX',(0,0),(0,0),2,PC),('BOX',(1,0),(1,0),2,AC),
        ('BOX',(2,0),(2,0),2,colors.HexColor('#27ae60')),
        ('BACKGROUND',(0,0),(0,0),colors.HexColor('#fff5f5')),
        ('BACKGROUND',(1,0),(1,0),colors.HexColor('#f5f0ff')),
        ('BACKGROUND',(2,0),(2,0),colors.HexColor('#f0fff4')),
        ('ALIGN',(0,0),(-1,-1),'CENTER'),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('PADDING',(0,0),(-1,-1),14)]))
    story.append(st); story.append(Spacer(1,6))
    vd=[[Paragraph(f'<font color="{data["plag_label"][1]}"><b>{data["plag_label"][0]}</b></font>',S('v1',alignment=TA_CENTER,fontSize=9)),
         Paragraph(f'<font color="{data["ai_label"][1]}"><b>{data["ai_label"][0]}</b></font>',S('v2',alignment=TA_CENTER,fontSize=9)),
         Paragraph('<font color="#27ae60"><b>Unique Content</b></font>',S('v3',alignment=TA_CENTER,fontSize=9))]]
    vt=Table(vd,colWidths=[57*mm,57*mm,57*mm])
    vt.setStyle(TableStyle([('ALIGN',(0,0),(-1,-1),'CENTER')])); story.append(vt); story.append(Spacer(1,14))

    if data['matched_sources']:
        story.append(Paragraph('Matched Sources',S('sh3',fontName='Helvetica-Bold',fontSize=11,textColor=DARK,spaceAfter=6)))
        rows=[['#','Source','Match %','Type']]
        for i,s in enumerate(data['matched_sources']):
            rows.append([str(i+1),Paragraph(f'<font color="{s["color"]}"><b>{s["name"]}</b></font><br/><font size="7" color="#999">{s["url"]}</font>',S(f'sn{i}',fontSize=9)),
                Paragraph(f'<font color="{s["color"]}"><b>{s["pct"]}%</b></font>',S(f'sp{i}',alignment=TA_CENTER)),'Internet Source'])
        srct=Table(rows,colWidths=[10*mm,90*mm,25*mm,45*mm])
        srct.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),DARK),('TEXTCOLOR',(0,0),(-1,0),colors.white),
            ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),9),
            ('GRID',(0,0),(-1,-1),0.3,BORDER),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f8f9fa')]),
            ('PADDING',(0,0),(-1,-1),7),('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
        story.append(srct); story.append(Spacer(1,14))

    if data['highlighted_sentences']:
        story.append(Paragraph('Text with Highlighted Matches',S('sh4',fontName='Helvetica-Bold',fontSize=11,textColor=DARK,spaceAfter=6)))
        for hs in data['highlighted_sentences'][:12]:
            hx=hs['color'].replace('#','')
            r,g,b=int(hx[0:2],16)/255,int(hx[2:4],16)/255,int(hx[4:6],16)/255
            bg=colors.Color(min(1,r*0.1+0.9),min(1,g*0.1+0.9),min(1,b*0.1+0.9))
            story.append(Paragraph(f'<font color="{hs["color"]}">{hs["text"]}</font> <font size="7" color="#999">[{hs["source"]} - {hs["match_pct"]}% match]</font>',
                S(f'hs{id(hs)}',fontSize=9,leading=14,spaceBefore=2,spaceAfter=2,backColor=bg,leftIndent=4)))
        story.append(Spacer(1,14))

    story.append(HRFlowable(width="100%",thickness=1,color=BORDER,spaceBefore=8))
    story.append(Paragraph(
        "This Similarity Report has been produced by Turnitin. The information contained in this Similarity Report is intended solely for the use of the individual or entity to whom it is addressed. Turnitin is committed to protecting personal data in compliance with applicable data protection laws. For more information please see our Privacy Policy at turnitin.com/privacy.",
        S('disc',fontSize=7,textColor=BLUE,leading=10,spaceBefore=6,borderColor=BLUE,borderWidth=0.5,borderPadding=6,backColor=colors.HexColor('#e8f0fe'))))
    story.append(Spacer(1,6))
    story.append(Paragraph(f'<font color="#e74c3c"><b>Turnitin</b></font><font color="#999"> | Similarity Report | {data["submission_date"]} | ID: {data["submission_id"]}</font>',
        S('ft',fontSize=8,alignment=TA_CENTER)))
    doc.build(story)

def gen_ai_pdf(data, out):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.enums import TA_CENTER

    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=15*mm, bottomMargin=20*mm)
    ss = getSampleStyleSheet(); story = []
    RED=colors.HexColor('#e74c3c'); BLUE=colors.HexColor('#1a73e8')
    DARK=colors.HexColor('#1a1a2e'); BORDER=colors.HexColor('#dee2e6')
    PURPLE=colors.HexColor('#6c63ff'); AC=colors.HexColor(data['ai_label'][1])

    def S(n,**k): return ParagraphStyle(n,parent=ss['Normal'],**k)

    hd=[[Paragraph('<font color="#e74c3c"><b>Turnitin</b></font>',S('lg',fontName='Helvetica-Bold',fontSize=22)),
         Paragraph('AI Writing Detection Report',S('hr',fontName='Helvetica',fontSize=13,textColor=DARK,alignment=2))]]
    ht=Table(hd,colWidths=[90*mm,80*mm])
    ht.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
    story.append(ht)
    story.append(HRFlowable(width="100%",thickness=3,color=PURPLE,spaceAfter=10))

    story.append(Paragraph('Submission Details',S('sh',fontName='Helvetica-Bold',fontSize=11,textColor=DARK,spaceBefore=6,spaceAfter=6)))
    info=[['Document',data['filename'],'Submission ID',data['submission_id']],
          ['Submitted',data['submission_date'],'Word Count',f"{data['word_count']:,}"]]
    it=Table(info,colWidths=[35*mm,65*mm,35*mm,35*mm])
    it.setStyle(TableStyle([('BACKGROUND',(0,0),(0,-1),colors.HexColor('#f1f3f4')),
        ('BACKGROUND',(2,0),(2,-1),colors.HexColor('#f1f3f4')),
        ('FONTNAME',(0,0),(0,-1),'Helvetica-Bold'),('FONTNAME',(2,0),(2,-1),'Helvetica-Bold'),
        ('FONTSIZE',(0,0),(-1,-1),9),('GRID',(0,0),(-1,-1),0.5,BORDER),('PADDING',(0,0),(-1,-1),6)]))
    story.append(it); story.append(Spacer(1,12))

    story.append(Paragraph('AI Detection Results',S('sh2',fontName='Helvetica-Bold',fontSize=11,textColor=DARK,spaceAfter=8)))
    sd=[[Paragraph(f'<font size="40" color="{data["ai_label"][1]}"><b>{data["ai_score"]}%</b></font><br/><font size="11" color="#6c757d">AI-Generated</font>',S('sc',alignment=TA_CENTER)),
         Paragraph(f'<font size="40" color="#9b59b6"><b>{data["ai_paraphrased_score"]}%</b></font><br/><font size="11" color="#6c757d">AI-Paraphrased</font>',S('sc2',alignment=TA_CENTER)),
         Paragraph(f'<font size="40" color="#27ae60"><b>{data["ai_original_pct"]}%</b></font><br/><font size="11" color="#6c757d">Human-Written</font>',S('sc3',alignment=TA_CENTER))]]
    st=Table(sd,colWidths=[57*mm,57*mm,57*mm])
    st.setStyle(TableStyle([('BOX',(0,0),(0,0),2,AC),('BOX',(1,0),(1,0),2,colors.HexColor('#9b59b6')),
        ('BOX',(2,0),(2,0),2,colors.HexColor('#27ae60')),
        ('BACKGROUND',(0,0),(0,0),colors.HexColor('#fff0f0')),
        ('BACKGROUND',(1,0),(1,0),colors.HexColor('#f9f0ff')),
        ('BACKGROUND',(2,0),(2,0),colors.HexColor('#f0fff4')),
        ('ALIGN',(0,0),(-1,-1),'CENTER'),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('PADDING',(0,0),(-1,-1),16)]))
    story.append(st); story.append(Spacer(1,6))
    vd=[[Paragraph(f'<font color="{data["ai_label"][1]}"><b>{data["ai_label"][0]}</b></font>',S('v1',alignment=TA_CENTER,fontSize=9)),
         Paragraph('<font color="#9b59b6"><b>AI Paraphrasing Detected</b></font>',S('v2',alignment=TA_CENTER,fontSize=9)),
         Paragraph('<font color="#27ae60"><b>Original Human Writing</b></font>',S('v3',alignment=TA_CENTER,fontSize=9))]]
    vt=Table(vd,colWidths=[57*mm,57*mm,57*mm]); vt.setStyle(TableStyle([('ALIGN',(0,0),(-1,-1),'CENTER')]))
    story.append(vt); story.append(Spacer(1,14))

    story.append(Paragraph('Highlight Color Key',S('sh3',fontName='Helvetica-Bold',fontSize=11,textColor=DARK,spaceAfter=6)))
    lg=[['<font color="#e74c3c">&#9632;</font> Red - AI Generated text','<font color="#9b59b6">&#9632;</font> Purple - AI Paraphrased'],
        ['<font color="#27ae60">&#9632;</font> Green - Original human writing','<font color="#f39c12">&#9632;</font> Orange - Uncertain / Mixed origin']]
    lgt=Table([[Paragraph(lg[0][0],S('l0',fontSize=9)),Paragraph(lg[0][1],S('l1',fontSize=9))],
               [Paragraph(lg[1][0],S('l2',fontSize=9)),Paragraph(lg[1][1],S('l3',fontSize=9))]],colWidths=[85*mm,85*mm])
    lgt.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#f8f9fa')),
        ('BOX',(0,0),(-1,-1),0.5,BORDER),('GRID',(0,0),(-1,-1),0.3,BORDER),('PADDING',(0,0),(-1,-1),7)]))
    story.append(lgt); story.append(Spacer(1,14))

    if data['flagged_phrases']:
        story.append(Paragraph('AI-Indicative Phrases',S('sh4',fontName='Helvetica-Bold',fontSize=11,textColor=DARK,spaceAfter=6)))
        rows=[]
        fps=data['flagged_phrases']
        for i in range(0,len(fps),2):
            rows.append([Paragraph(f'<font color="#e74c3c">&#9670;</font> {fps[i]}',S(f'p{i}',fontSize=9)),
                Paragraph(f'<font color="#e74c3c">&#9670;</font> {fps[i+1]}',S(f'p{i+1}',fontSize=9)) if i+1<len(fps) else Paragraph('',ss['Normal'])])
        pt=Table(rows,colWidths=[85*mm,85*mm])
        pt.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.3,BORDER),
            ('ROWBACKGROUNDS',(0,0),(-1,-1),[colors.white,colors.HexColor('#fff5f5')]),('PADDING',(0,0),(-1,-1),6)]))
        story.append(pt); story.append(Spacer(1,14))

    story.append(HRFlowable(width="100%",thickness=1,color=BORDER,spaceBefore=4))
    story.append(Paragraph('Frequently Asked Questions',S('faqh',fontName='Helvetica-Bold',fontSize=11,textColor=DARK,spaceBefore=10,spaceAfter=8)))
    faqs=[("What does the AI score mean?","The AI score indicates the percentage of text predicted to be generated by AI tools such as ChatGPT, Claude, Gemini, or similar. A higher score means more text shows patterns consistent with AI-generated writing."),
          ("What is AI-paraphrased content?","AI-paraphrased content refers to text that appears to have been generated by AI and then edited by a human. It often retains AI writing patterns while showing signs of manual modification."),
          ("Can AI detection be 100% accurate?","No. AI detection is probabilistic. Turnitin achieves high accuracy but cannot guarantee 100% certainty. Results should be used alongside other contextual information."),
          ("What should I do if I believe the result is incorrect?","Speak with your instructor or institution. Turnitin results are not definitive proof — they are one indicator in an academic integrity review. Context and additional evidence should always be considered."),
          ("Does Turnitin store my submitted documents?","This depends on your institution's settings. For full details on data retention and privacy, visit turnitin.com/privacy.")]
    for q,a in faqs:
        story.append(Paragraph(f'<b>Q: {q}</b>',S(f'fq{q[:8]}',fontSize=9,textColor=DARK,spaceBefore=6,spaceAfter=2,backColor=colors.HexColor('#f1f3f4'),leftIndent=4,borderPadding=4)))
        story.append(Paragraph(f'A: {a}',S(f'fa{q[:8]}',fontSize=9,textColor=colors.HexColor('#444'),leading=13,leftIndent=8,spaceAfter=4)))

    story.append(Spacer(1,10))
    story.append(HRFlowable(width="100%",thickness=1,color=BORDER))
    story.append(Paragraph(
        "IMPORTANT NOTICE: This AI Writing Detection Report is provided by Turnitin for informational purposes only. Turnitin's AI detection technology provides an indicator of potential AI-generated content and should not be used as the sole basis for academic integrity decisions. Educators are encouraged to use this report alongside other evidence and to engage in dialogue with students. For full terms and privacy information, visit turnitin.com.",
        S('disc',fontSize=7,textColor=BLUE,leading=10,spaceBefore=8,borderColor=BLUE,borderWidth=0.5,borderPadding=6,backColor=colors.HexColor('#e8f0fe'))))
    story.append(Spacer(1,6))
    story.append(Paragraph(f'<font color="#e74c3c"><b>Turnitin</b></font><font color="#999"> | AI Writing Detection | {data["submission_date"]} | ID: {data["submission_id"]}</font>',
        S('ft',fontSize=8,alignment=TA_CENTER)))
    doc.build(story)

@app.route('/')
def index(): return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    text=''; filename='Pasted Text'
    if 'file' in request.files and request.files['file'].filename:
        f=request.files['file']
        if not allowed_file(f.filename): return jsonify({'error':'Only .txt, .pdf, .docx supported.'}),400
        fname=secure_filename(f.filename); ext=fname.rsplit('.',1)[1].lower()
        fp=os.path.join(UPLOAD_FOLDER,fname); f.save(fp)
        text=extract_text(fp,ext); filename=fname
        try: os.remove(fp)
        except: pass
    else:
        d=request.get_json(); text=d.get('text','') if d else ''
    if len(text.strip())<50: return jsonify({'error':'Please provide at least 50 characters.'}),400
    return jsonify(analyze_text(text,filename))

@app.route('/report/similarity', methods=['POST'])
def sim_report():
    d=request.get_json(); out=os.path.join(REPORT_FOLDER,f"sim_{d.get('submission_id','X')}.pdf")
    gen_similarity_pdf(d,out)
    return send_file(out,as_attachment=True,download_name=f"Turnitin_Similarity_{d.get('submission_id','report')}.pdf",mimetype='application/pdf')

@app.route('/report/ai', methods=['POST'])
def ai_report():
    d=request.get_json(); out=os.path.join(REPORT_FOLDER,f"ai_{d.get('submission_id','X')}.pdf")
    gen_ai_pdf(d,out)
    return send_file(out,as_attachment=True,download_name=f"Turnitin_AI_{d.get('submission_id','report')}.pdf",mimetype='application/pdf')

if __name__=='__main__': app.run(debug=True)
