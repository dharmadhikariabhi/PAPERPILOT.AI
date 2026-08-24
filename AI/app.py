import os
import sys
import io
import json
import base64
import time
import requests
import threading
import webbrowser
import pypdfium2 as pdfium
import google.generativeai as genai
from flask import Flask, request, jsonify, Response
from PIL import Image
import webview

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, static_folder=BASE_DIR, static_url_path='')


@app.route('/')
def home():
    paths_to_check = [
        os.path.join(BASE_DIR, 'index.html'),
        os.path.join(BASE_DIR, 'templates', 'index.html')
    ]
    for file_path in paths_to_check:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return Response(f.read(), mimetype='text/html')
                
    return "<h2 style='color:red; text-align:center;'>❌ index.html सापडली नाही!</h2>", 404

@app.route('/transliterate', methods=['POST'])
def transliterate():
    try:
        data = request.json
        text = data.get('text', '')
        if not text:
            return jsonify({'result': ''})

        url = f"https://inputtools.google.com/request?text={requests.utils.quote(text)}&itc=mr-t-i0-und&num=1&cp=0&cs=1&ie=utf-8&oe=utf-8&app=test"
        res = requests.get(url, timeout=5)
        res_json = res.json()

        if res_json and res_json[0] == "SUCCESS" and res_json[1][0][1]:
            converted_text = res_json[1][0][1][0]
            return jsonify({'result': converted_text})
        
        return jsonify({'result': text})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/generate-paper', methods=['POST'])
def generate_paper():
    try:
        data = request.json
        api_keys = data.get('api_keys', [])
        base64_format = data.get('base64_format')
        handwritten_list = data.get('handwritten_list', [])
        pdf_base64 = data.get('pdf_base64')

        if not api_keys:
            return jsonify({'error': 'Please add at least one Gemini API Key!'}), 400

        images_data = []

        # Optional Format Image
        if base64_format:
            images_data.append(Image.open(io.BytesIO(base64.b64decode(base64_format))))

        # PDF or Images Extract
        if pdf_base64:
            pdf_bytes = base64.b64decode(pdf_base64)
            pdf = pdfium.PdfDocument(pdf_bytes)
            for page_idx in range(len(pdf)):
                page = pdf[page_idx]
                image = page.render(scale=2).to_pil()
                images_data.append(image)
        elif handwritten_list:
            for item in handwritten_list:
                img_bytes = base64.b64decode(item['data'])
                images_data.append(Image.open(io.BytesIO(img_bytes)))

        if not images_data:
            return jsonify({'error': 'No document image or PDF provided!'}), 400

        # 🔴 STRICT CONTINUOUS NATURAL FLOW PROMPT (ZERO UNWANTED GAPS)
        core_prompt = f"""
            YOU ARE A PROFESSIONAL SCHOOL EXAM QUESTION PAPER TYPIST.
            The user uploaded {len(images_data)} image(s) of exam questions.

            CRITICAL CONTINUOUS FLOW RULES (DO NOT LEAVE GAPS):
            1. SEAMLESS NATURAL FLOW:
               - Transcribe ALL questions continuously from Q.1 to the last question.
               - DO NOT create separate empty page boxes or force artificial page breaks between images.
               - If image 1 ends halfway, image 2's content MUST continue immediately below it without leaving any large blank white gaps.

            2. 100% ACCURATE VERBATIM TRANSCRIPTION:
               - Transcribe ONLY what is physically written on the uploaded images.
               - DO NOT add fake questions, extra paragraphs, or sample text not written by the teacher.

            3. STRIP ALL NOTEBOOK BRANDING & METADATA:
               - REMOVE notebook brand names (Classmate, Veda, Sundaram, Navneet, Target, etc.).
               - REMOVE page numbers written on notebook corners (e.g. Pg 1, 1/3, Date, Page No).
               - REMOVE stray pencil scratches or background margins.

            4. CLEAN QUESTION PAPER FORMATTING:
               - School Header (if present at top of image 1): Centered and bold.
               - Main Questions (Q.1, Q.2 / प्र. १, प्र. २): <b>Bold</b> with marks aligned to the right: <span style="float:right;">[Marks]</span>.
               - Sub-questions (1, 2, a, b, i, ii): Indented neatly with margin-left: 20px.
               - MCQ Options: If written horizontally, keep in a clean single line with spacing:
                 <div style="margin-left:30px; margin-top:4px; margin-bottom:6px;">(A) [Opt 1] &nbsp;&nbsp;&nbsp;&nbsp; (B) [Opt 2] &nbsp;&nbsp;&nbsp;&nbsp; (C) [Opt 3] &nbsp;&nbsp;&nbsp;&nbsp; (D) [Opt 4]</div>
               - Tables: Clean tables with thin border (`<table style="width:100%; border-collapse:collapse; margin:8px 0;">`).
               - Diagrams: Centered clean inline SVG (`<svg ...>`).

            5. OUTPUT FORMAT:
               - Return ONLY raw HTML markup without markdown fences (```html).
        """

        generated_html = ""
        success = False
        last_error = ""

        for key in api_keys:
            try:
                genai.configure(api_key=key)
                available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]

                if not available_models:
                    last_error = "No active models found for this API Key."
                    continue

                chosen_model_name = available_models[0]
                for m_name in available_models:
                    if 'flash' in m_name.lower():
                        chosen_model_name = m_name
                        break

                model = genai.GenerativeModel(chosen_model_name)
                content_payload = [core_prompt] + images_data
                
                response = model.generate_content(
                    content_payload,
                    generation_config={"max_output_tokens": 8192}
                )
                
                generated_html = response.text.replace("```html", "").replace("```", "").strip()
                success = True
                break
            except Exception as e:
                last_error = str(e)
                continue

        if not success:
            return jsonify({'error': f'All API keys failed. Last error: {last_error}'}), 500

        return jsonify({'status': 'success', 'html': generated_html})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/save-word-file', methods=['POST'])
def save_word_file():
    try:
        data = request.json
        html_content = data.get('html_content', '')
        filename = data.get('filename', 'Exam_Paper.doc')
        watermark_text = data.get('watermark_text', '')

        base_name, ext = os.path.splitext(filename)
        if not ext or ext.lower() not in ['.doc', '.docx']:
            ext = '.doc'

        desktop_path = os.path.join(os.path.expanduser('~'), 'Desktop')
        onedrive_desktop = os.path.join(os.path.expanduser('~'), 'OneDrive', 'Desktop')
        if os.path.exists(onedrive_desktop):
            desktop_path = onedrive_desktop

        os.makedirs(desktop_path, exist_ok=True)
        output_path = os.path.join(desktop_path, f"{base_name}{ext}")

        if os.path.exists(output_path):
            try:
                with open(output_path, 'a', encoding='utf-8'):
                    pass
            except PermissionError:
                timestamp = time.strftime("%H%M%S")
                output_path = os.path.join(desktop_path, f"{base_name}_{timestamp}{ext}")

        word_html = f"""
        <html xmlns:o='urn:schemas-microsoft-com:office:office' xmlns:w='urn:schemas-microsoft-com:office:word' xmlns='[http://www.w3.org/TR/REC-html40](http://www.w3.org/TR/REC-html40)'>
        <head>
            <meta charset="utf-8">
            <title>Exam Paper</title>
            <style>
                @page Section1 {{
                    size: 595.3pt 841.9pt;
                    margin: 36.0pt 40.0pt 36.0pt 40.0pt;
                }}
                div.Section1 {{ page: Section1; }}
                body {{ 
                    font-family: 'Times New Roman', 'Mangal', 'Nirmala UI', serif; 
                    font-size: 13pt; 
                    line-height: 1.35; 
                }}
                table {{ 
                    width: 100%; 
                    border-collapse: collapse; 
                }}
                td, th {{ 
                    border: 1px solid #000;
                    padding: 4px 6px; 
                    vertical-align: middle; 
                }}
            </style>
        </head>
        <body>
            <div class="Section1">
                {f'<div style="text-align:center; color:#e2e8f0; font-size:36pt; font-weight:bold; margin-bottom:10px;">{watermark_text}</div>' if watermark_text else ''}
                {html_content}
            </div>
        </body>
        </html>
        """

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(word_html)

        return jsonify({'status': 'success', 'path': output_path})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = 5050
    server_thread = threading.Thread(target=lambda: app.run(host='127.0.0.1', port=port, debug=False))
    server_thread.daemon = True
    server_thread.start()

    webview.create_window('PaperPilot.AI', f'http://127.0.0.1:{port}', width=1300, height=850, resizable=True)
    webview.start()