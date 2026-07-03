#!/usr/bin/env python3
"""
JupyterHub Quiz Service
-----------------------
Routes (all under JUPYTERHUB_SERVICE_PREFIX, e.g. /hub/services/quiz/):

  GET  /                - Quiz page: all questions on one page
  POST /submit          - Score answers, append attempt to user JSON, return result
  GET  /results         - Admin results viewer (QUIZ_ADMIN_USER only)
  GET  /oauth_callback  - Hub OAuth callback

Env vars set by JupyterHub automatically + service config:
  JUPYTERHUB_SERVICE_PREFIX, JUPYTERHUB_SERVICE_PORT
  QUIZ_DATA_DIR    (default /srv/jupyterhub/quiz_data)
  QUIZ_RESULT_DIR  (default /srv/jupyterhub/quiz_result)
  QUIZ_ADMIN_USER  (default eg2577)
  QUIZ_PASS_THRESHOLD (default 0.8)
"""

import datetime
import html as _html
import json
import os
import pathlib

from jupyterhub.services.auth import HubOAuthenticated, HubOAuthCallbackHandler
from tornado import ioloop, web

# Config
QUIZ_DATA_DIR   = pathlib.Path(os.environ.get("QUIZ_DATA_DIR",   "/srv/jupyterhub/quiz_data"))
QUIZ_RESULT_DIR = pathlib.Path(os.environ.get("QUIZ_RESULT_DIR", "/srv/jupyterhub/quiz_result"))
ADMIN_USER      = os.environ.get("QUIZ_ADMIN_USER", "eg2577")
PASS_THRESHOLD  = float(os.environ.get("QUIZ_PASS_THRESHOLD", "0.8"))

# --------------------------------------------------------------------------
# Data helpers
# --------------------------------------------------------------------------

def _load_questions(stage, chapter):
    path = QUIZ_DATA_DIR / f"s{stage}c{chapter}.json"
    if path.exists():
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    return []

def _result_path(username):
    QUIZ_RESULT_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in username if c.isalnum() or c in "-_.")
    return QUIZ_RESULT_DIR / f"{safe}.json"

def _load_user_results(username):
    path = _result_path(username)
    if path.exists():
        try:
            with path.open(encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                data = json.loads(content)
                if isinstance(data, dict):
                    return data
        except (json.JSONDecodeError, ValueError):
            pass
    return {"username": username, "attempts": []}

def _save_user_results(data):
    path = _result_path(data["username"])
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def _list_result_users():
    QUIZ_RESULT_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(p.stem for p in QUIZ_RESULT_DIR.glob("*.json"))

# --------------------------------------------------------------------------
# HTML helpers
# --------------------------------------------------------------------------

def _e(s):
    return _html.escape(str(s))

def _chapter_options_html(stage, current_chapter):
    n = {1: 10, 2: 10, 3: 5}.get(stage, 10)
    return "\n".join(
        '<option value="{}"{}>{}</option>'.format(
            i, " selected" if i == current_chapter else "", "Chapter " + str(i)
        )
        for i in range(1, n + 1)
    )

def _quiz_questions_html(questions):
    if not questions:
        return '<p style="color:#6b7280;text-align:center;padding:2rem 0">No questions found for this chapter.</p>'
    parts = []
    for i, q in enumerate(questions):
        opts = ""
        for key, text in q["options"].items():
            opts += (
                '<div class="opt-wrap">'
                '<input type="radio" name="q{i}" id="q{i}k{key}" value="{key}">'
                '<label for="q{i}k{key}" class="opt-label">'
                '<span class="opt-badge">{key}</span>'
                '<span>{text}</span>'
                "</label></div>"
            ).format(i=i, key=key, text=_e(text))
        parts.append(
            '<div class="q-card" id="qcard-{i}">'
            '<div class="q-num">Question {n}</div>'
            '<div class="q-text">{qt}</div>'
            '<div class="opts">{opts}</div>'
            "</div>"
            .format(i=i, n=i+1, qt=_e(q["question"]), opts=opts)
        )
    return "\n".join(parts)

def _attempt_review_html(attempt, username=""):
    score  = attempt["score"]
    total  = attempt["total"]
    passed = attempt["passed"]
    pct    = round(score / total * 100) if total else 0
    pass_cls  = "pass" if passed else "fail"
    pass_icon = "&#10003;" if passed else "&#10007;"

    q_parts = []
    for j, a in enumerate(attempt.get("answers", [])):
        opts_html = ""
        for key, text in a.get("options", {}).items():
            is_correct  = key == a.get("correct_answer")
            is_selected = key == a.get("selected")

            cls  = "ra-opt"
            tag  = ""
            if is_correct and is_selected:
                cls += " ra-correct ra-chosen"
                tag = '<span class="ra-tag ra-ok">&#10003; Correct &middot; Your Answer</span>'
            elif is_correct:
                cls += " ra-correct"
                tag = '<span class="ra-tag ra-ok">&#10003; Correct Answer</span>'
            elif is_selected:
                cls += " ra-wrong ra-chosen"
                tag = '<span class="ra-tag ra-err">&#10007; Your Answer</span>'

            badge_cls = "ra-badge" + (" ra-badge-ok" if is_correct else " ra-badge-err" if is_selected else "")
            text_inner = "<strong>{}</strong>".format(_e(text)) if is_correct else _e(text)
            opts_html += (
                '<div class="{cls}"><span class="{bc}">{key}</span>'
                '<span class="ra-opt-text">{ti}</span>{tag}</div>'
            ).format(cls=cls, bc=badge_cls, key=key, ti=text_inner, tag=tag)

        q_parts.append(
            '<div class="ra-q">'
            '<p class="ra-q-num">Q{n}</p>'
            '<p class="ra-q-text">{qt}</p>'
            '<div class="ra-opts">{opts}</div>'
            "</div>"
            .format(n=j+1, qt=_e(a.get("question","")), opts=opts_html)
        )

    return (
        '<details class="attempt-wrap">'
        '<summary class="attempt-sum">'
        "<span>Attempt {at} &nbsp;&middot;&nbsp; {ts} &nbsp;&middot;&nbsp; Stage {stg}, Chapter {ch}</span>"
        '<div style="display:flex;align-items:center;gap:.5rem">'
        '<span class="attempt-score {pc}">{sc}/{tot} ({pct}%) {pi}</span>'
        '<button class="btn-del" onclick="event.stopPropagation();deleteAttempt(&#39;{user}&#39;,{at})">&#128465; Delete</button>'
        '</div>'
        "</summary>"
        '<div class="attempt-body">{body}</div>'
        "</details>"
    ).format(
        at=attempt["attempt"], ts=_e(attempt.get("timestamp","")),
        stg=attempt.get("stage","?"), ch=attempt.get("chapter","?"),
        pc=pass_cls, sc=score, tot=total, pct=pct, pi=pass_icon,
        body="\n".join(q_parts),
        user=_e(username)
    )

def _render_quiz_page(username, prefix, stage, chapter, questions):
    pfx = prefix.rstrip("/") + "/"
    admin_link = (
        '<a class="nav-link" href="{}results">&#128202; Results</a>'.format(pfx)
        if username == ADMIN_USER else ""
    )
    return (
        _QUIZ_TEMPLATE
        .replace("__USERNAME__",        _e(username))
        .replace("__PREFIX__",          pfx)
        .replace("__ADMIN_LINK__",      admin_link)
        .replace("__S1__",              " selected" if stage == 1 else "")
        .replace("__S2__",              " selected" if stage == 2 else "")
        .replace("__S3__",              " selected" if stage == 3 else "")
        .replace("__CHAPTER_OPTIONS__", _chapter_options_html(stage, chapter))
        .replace("__QUESTIONS_HTML__",  _quiz_questions_html(questions))
        .replace("__STAGE__",           str(stage))
        .replace("__CHAPTER__",         str(chapter))
        .replace("__SUBMIT_DISABLED__", "" if questions else "disabled")
    )

def _render_results_page(username, prefix, users, selected_user, user_data):
    pfx = prefix.rstrip("/") + "/"
    user_opts = (
        '<option value="">&#8212; select a student &#8212;</option>\n'
        + "\n".join(
            '<option value="{v}"{sel}>{v}</option>'.format(
                v=_e(u), sel=" selected" if u == selected_user else ""
            )
            for u in users
        )
    )
    student_section = ""
    if selected_user:
        attempts = (user_data or {}).get("attempts", [])
        if attempts:
            attempts_html = "\n".join(_attempt_review_html(a, selected_user) for a in reversed(attempts))
        else:
            attempts_html = '<p style="color:#6b7280;text-align:center;padding:2rem">No attempts found.</p>'
        student_section = (
            '<div class="card">'
            '<h2 class="section-title">Results for {u}</h2>'
            "{ah}</div>"
        ).format(u=_e(selected_user), ah=attempts_html)

    return (
        _RESULTS_TEMPLATE
        .replace("__USERNAME__",       _e(username))
        .replace("__PREFIX__",         pfx)
        .replace("__USER_OPTIONS__",   user_opts)
        .replace("__STUDENT_SECTION__", student_section)
    )

# --------------------------------------------------------------------------
# HTML templates (no f-strings; use __PLACEHOLDER__ .replace() substitution)
# --------------------------------------------------------------------------

_COMMON_CSS = """
:root {
  --primary:#4f46e5; --primary-h:#4338ca;
  --surface:#fff; --bg:#f0f2f9;
  --text:#1e1b4b; --muted:#6b7280;
  --ok:#16a34a; --err:#dc2626;
  --radius:12px;
}
*{box-sizing:border-box;margin:0;padding:0;}
body{
  font-family:"Segoe UI",system-ui,sans-serif;
  background:var(--bg);color:var(--text);
  min-height:100vh;padding:2rem 1rem;
  display:flex;flex-direction:column;align-items:center;
}
.hdr{
  width:100%;max-width:760px;background:var(--primary);color:#fff;
  border-radius:var(--radius);padding:1.2rem 1.8rem;margin-bottom:1.5rem;
  display:flex;justify-content:space-between;align-items:center;
}
.hdr h1{font-size:1.25rem;font-weight:700;}
.hdr .right{display:flex;align-items:center;gap:1rem;}
.hdr .welcome{font-size:.9rem;opacity:.9;}
.nav-link{font-size:.82rem;color:#c7d2fe;text-decoration:none;opacity:.9;}
.nav-link:hover{opacity:1;text-decoration:underline;}
.card{
  width:100%;max-width:760px;background:var(--surface);
  border-radius:var(--radius);box-shadow:0 4px 24px rgba(79,70,229,.08);
  padding:1.5rem 1.75rem;margin-bottom:1rem;
}
.sel-row{display:flex;gap:.75rem;align-items:flex-end;flex-wrap:wrap;}
.sel-row label{font-size:.8rem;font-weight:600;color:var(--muted);display:flex;flex-direction:column;gap:4px;}
.sel-row select{border:1.5px solid #d1d5db;border-radius:8px;padding:.4rem .75rem;font-size:.95rem;color:var(--text);outline:none;}
.sel-row select:focus{border-color:var(--primary);}
.btn-load{background:var(--primary);color:#fff;border:none;border-radius:8px;padding:.45rem 1.2rem;font-size:.9rem;font-weight:600;cursor:pointer;}
.btn-load:hover{background:var(--primary-h);}
.btn-del{background:var(--err);color:#fff;border:none;border-radius:6px;padding:.2rem .6rem;font-size:.78rem;font-weight:600;cursor:pointer;flex-shrink:0;}
.btn-del:hover{opacity:.85;}
"""

_QUIZ_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Python Quiz</title>
<style>
""" + _COMMON_CSS + """
.q-card{
  width:100%;max-width:760px;background:var(--surface);
  border-radius:var(--radius);box-shadow:0 2px 12px rgba(79,70,229,.06);
  padding:1.4rem 1.75rem;margin-bottom:.85rem;
  border:1.5px solid transparent;transition:border-color .2s;
}
.q-card.unanswered{border-color:var(--err);}
.q-num{font-size:.75rem;font-weight:700;color:var(--primary);text-transform:uppercase;letter-spacing:.07em;margin-bottom:.5rem;}
.q-text{font-size:.98rem;font-weight:600;line-height:1.65;white-space:pre-wrap;margin-bottom:1rem;}
.opts{display:flex;flex-direction:column;gap:.5rem;}
.opt-wrap input[type=radio]{display:none;}
.opt-label{
  display:flex;align-items:center;gap:.75rem;
  padding:.6rem 1rem;border:1.5px solid #d1d5db;
  border-radius:8px;cursor:pointer;font-size:.93rem;
  transition:border-color .12s,background .12s;
}
.opt-label:hover{border-color:#818cf8;background:#eef2ff;}
.opt-badge{
  min-width:26px;height:26px;display:flex;align-items:center;justify-content:center;
  border-radius:50%;background:#e5e7eb;font-size:.8rem;font-weight:700;flex-shrink:0;
  transition:background .12s,color .12s;
}
input[type=radio]:checked+.opt-label{border-color:var(--primary);background:#eef2ff;}
input[type=radio]:checked+.opt-label .opt-badge{background:var(--primary);color:#fff;}
.submit-wrap{width:100%;max-width:760px;margin-bottom:2rem;}
.btn-submit{width:100%;padding:.85rem;background:var(--primary);color:#fff;border:none;border-radius:10px;font-size:1.05rem;font-weight:700;cursor:pointer;}
.btn-submit:hover{background:var(--primary-h);}
.btn-submit:disabled{opacity:.45;cursor:default;}
#result-panel{display:none;width:100%;max-width:760px;border-radius:var(--radius);padding:2.5rem 2rem;text-align:center;margin-bottom:1.5rem;}
#result-panel.pass{background:#f0fdf4;border:2.5px solid var(--ok);}
#result-panel.fail{background:#fff1f2;border:2.5px solid var(--err);}
.result-icon{font-size:3.5rem;margin-bottom:.75rem;}
.result-title{font-size:1.6rem;font-weight:700;margin-bottom:.5rem;}
.result-score{font-size:1.1rem;margin-bottom:.75rem;color:var(--muted);}
.result-score strong{color:var(--text);}
.result-coach{color:var(--err);font-weight:700;font-size:1.05rem;margin-bottom:1rem;}
.btn-retry{background:var(--primary);color:#fff;border:none;border-radius:8px;padding:.55rem 1.6rem;font-size:.95rem;font-weight:700;cursor:pointer;}
.btn-retry:hover{background:var(--primary-h);}
</style>
</head>
<body>

<div class="hdr">
  <h1>&#128218; Python Learning Quiz</h1>
  <div class="right">
    <span class="welcome">Welcome, <strong>__USERNAME__</strong>!</span>
    __ADMIN_LINK__
  </div>
</div>

<div class="card">
  <div class="sel-row">
    <label>Stage
      <select id="sel-stage" onchange="updateChapterOpts()">
        <option value="1"__S1__>Stage 1</option>
        <option value="2"__S2__>Stage 2</option>
        <option value="3"__S3__>Stage 3</option>
      </select>
    </label>
    <label>Chapter
      <select id="sel-chapter">__CHAPTER_OPTIONS__</select>
    </label>
    <button class="btn-load" onclick="loadQuiz()">Load Quiz</button>
  </div>
</div>

<div id="result-panel"></div>
<div id="questions-wrap">__QUESTIONS_HTML__</div>

<div class="submit-wrap">
  <button class="btn-submit" id="submit-btn" __SUBMIT_DISABLED__ onclick="submitAnswers()">
    Submit Answers
  </button>
</div>

<script>
var PREFIX  = "__PREFIX__";
var STAGE   = __STAGE__;
var CHAPTER = __CHAPTER__;

function updateChapterOpts() {
  var stage = +document.getElementById('sel-stage').value;
  var counts = {1:10,2:10,3:5};
  var max = counts[stage]||10;
  var html='';
  for(var i=1;i<=max;i++) html+='<option value="'+i+'">Chapter '+i+'</option>';
  document.getElementById('sel-chapter').innerHTML=html;
}

function loadQuiz() {
  var s=document.getElementById('sel-stage').value;
  var c=document.getElementById('sel-chapter').value;
  window.location.href=PREFIX+'?stage='+s+'&chapter='+c;
}

function submitAnswers() {
  var cards=document.querySelectorAll('.q-card');
  if(!cards.length) return;
  cards.forEach(function(c){c.classList.remove('unanswered');});

  var missing=[];
  for(var i=0;i<cards.length;i++){
    if(!document.querySelector('input[name="q'+i+'"]:checked')) missing.push(i);
  }
  if(missing.length){
    missing.forEach(function(i){document.getElementById('qcard-'+i).classList.add('unanswered');});
    document.getElementById('qcard-'+missing[0]).scrollIntoView({behavior:'smooth',block:'center'});
    return;
  }

  var answers={};
  for(var i=0;i<cards.length;i++){
    answers[i]=document.querySelector('input[name="q'+i+'"]:checked').value;
  }

  var btn=document.getElementById('submit-btn');
  btn.disabled=true; btn.textContent='Submitting\u2026';

  fetch(PREFIX+'submit',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({stage:STAGE,chapter:CHAPTER,answers:answers})
  })
  .then(function(r){return r.json();})
  .then(function(data){showResult(data);})
  .catch(function(){btn.disabled=false;btn.textContent='Submit Answers';alert('Submission failed. Please try again.');});
}

function showResult(data) {
  document.getElementById('questions-wrap').style.display='none';
  document.querySelector('.submit-wrap').style.display='none';
  var panel=document.getElementById('result-panel');
  if(data.passed){
    panel.className='pass';
    panel.innerHTML=
      '<div class="result-icon">&#127881;</div>'+
      '<div class="result-title">Congratulations! You passed!</div>'+
      '<div class="result-score">You scored <strong>'+data.score+' out of '+data.total+
      '</strong> &nbsp;&middot;&nbsp; Attempt #'+data.attempt+'</div>'+
      '<button class="btn-retry" onclick="location.reload()">Try Again</button>';
  } else {
    panel.className='fail';
    panel.innerHTML=
      '<div class="result-icon">&#128221;</div>'+
      '<div class="result-title">Quiz Complete</div>'+
      '<div class="result-score">You scored <strong>'+data.score+' out of '+data.total+
      '</strong> &nbsp;&middot;&nbsp; Attempt #'+data.attempt+'</div>'+
      '<div class="result-coach">Please talk to the coach.</div>'+
      '<button class="btn-retry" onclick="location.reload()">Try Again</button>';
  }
  panel.style.display='block';
  window.scrollTo({top:0,behavior:'smooth'});
}
</script>
</body>
</html>"""

_RESULTS_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Quiz Results &#8212; Admin</title>
<style>
""" + _COMMON_CSS + """
.section-title{font-size:1.1rem;font-weight:700;margin-bottom:1.25rem;color:var(--primary);}
.attempt-wrap{border:1.5px solid #e5e7eb;border-radius:10px;margin-bottom:.85rem;overflow:hidden;}
.attempt-sum{
  display:flex;justify-content:space-between;align-items:center;
  padding:1rem 1.25rem;cursor:pointer;list-style:none;
  font-size:.93rem;font-weight:600;background:#f8f9ff;user-select:none;
}
.attempt-sum::-webkit-details-marker{display:none;}
.attempt-sum:hover{background:#eef2ff;}
.attempt-score{font-size:.85rem;font-weight:700;padding:.25rem .7rem;border-radius:99px;}
.attempt-score.pass{background:#dcfce7;color:var(--ok);}
.attempt-score.fail{background:#fee2e2;color:var(--err);}
.attempt-body{padding:1.25rem;display:flex;flex-direction:column;gap:1.1rem;}
.ra-q{border:1px solid #e5e7eb;border-radius:8px;padding:1rem 1.25rem;}
.ra-q-num{font-size:.72rem;font-weight:700;color:var(--primary);text-transform:uppercase;letter-spacing:.07em;margin-bottom:.35rem;}
.ra-q-text{font-size:.95rem;font-weight:600;line-height:1.6;white-space:pre-wrap;margin-bottom:.85rem;}
.ra-opts{display:flex;flex-direction:column;gap:.45rem;}
.ra-opt{display:flex;align-items:center;gap:.75rem;padding:.55rem .9rem;border:1.5px solid #e5e7eb;border-radius:8px;font-size:.92rem;}
.ra-opt.ra-correct{border-color:var(--ok);background:#f0fdf4;}
.ra-opt.ra-wrong{border-color:var(--err);background:#fff1f2;}
.ra-badge{min-width:26px;height:26px;display:flex;align-items:center;justify-content:center;border-radius:50%;background:#e5e7eb;font-size:.8rem;font-weight:700;flex-shrink:0;}
.ra-badge-ok{background:var(--ok);color:#fff;}
.ra-badge-err{background:var(--err);color:#fff;}
.ra-opt-text{flex:1;}
.ra-tag{font-size:.78rem;font-weight:700;white-space:nowrap;}
.ra-tag.ra-ok{color:var(--ok);}
.ra-tag.ra-err{color:var(--err);}
</style>
</head>
<body>

<div class="hdr">
  <h1>&#128202; Quiz Results <span style="font-size:.8rem;opacity:.7">(Admin)</span></h1>
  <div class="right">
    <span class="welcome">Welcome, <strong>__USERNAME__</strong>!</span>
    <a class="nav-link" href="__PREFIX__">&#8592; Back to Quiz</a>
  </div>
</div>

<div class="card">
  <form method="get" action="__PREFIX__results" class="sel-row">
    <label>Student
      <select name="user" onchange="this.form.submit()">
        __USER_OPTIONS__
      </select>
    </label>
  </form>
</div>

__STUDENT_SECTION__

<script>
function deleteAttempt(user, attemptNum) {
  if (!confirm('Delete attempt #' + attemptNum + ' for ' + user + '?')) return;
  fetch('__PREFIX__delete_attempt', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({user: user, attempt: attemptNum})
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    if (data.ok) { location.reload(); }
    else { alert('Error: ' + (data.error || 'Unknown error')); }
  })
  .catch(function() { alert('Delete failed. Please try again.'); });
}
</script>

</body>
</html>"""

# --------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------

class QuizHandler(HubOAuthenticated, web.RequestHandler):
    @web.authenticated
    def get(self):
        user = self.get_current_user()
        username = user.get("name", "Unknown")
        prefix = os.environ.get("JUPYTERHUB_SERVICE_PREFIX", "/")
        try:
            stage   = max(1, min(3,  int(self.get_argument("stage",   1))))
            chapter = max(1, min(10, int(self.get_argument("chapter", 1))))
        except (ValueError, TypeError):
            stage, chapter = 1, 1
        questions = _load_questions(stage, chapter)
        self.set_header("Content-Type", "text/html; charset=utf-8")
        self.write(_render_quiz_page(username, prefix, stage, chapter, questions))


class SubmitHandler(HubOAuthenticated, web.RequestHandler):
    @web.authenticated
    def post(self):
        user = self.get_current_user()
        username = user.get("name", "Unknown")
        try:
            body = json.loads(self.request.body)
        except (json.JSONDecodeError, ValueError):
            self.set_status(400); self.write({"error": "Invalid JSON"}); return
        try:
            stage   = max(1, min(3,  int(body.get("stage",   1))))
            chapter = max(1, min(10, int(body.get("chapter", 1))))
        except (ValueError, TypeError):
            stage, chapter = 1, 1
        selected  = body.get("answers", {})
        questions = _load_questions(stage, chapter)
        if not questions:
            self.set_status(404); self.write({"error": "Questions not found"}); return

        details = []
        correct_count = 0
        for i, q in enumerate(questions):
            chosen = selected.get(str(i))
            ok = chosen == q["answer"]
            if ok: correct_count += 1
            details.append({
                "question": q["question"], "options": q["options"],
                "correct_answer": q["answer"], "selected": chosen, "is_correct": ok,
            })

        total  = len(questions)
        passed = (correct_count / total) >= PASS_THRESHOLD if total else False

        user_data   = _load_user_results(username)
        attempt_num = len(user_data["attempts"]) + 1
        user_data["attempts"].append({
            "attempt":   attempt_num,
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "stage": stage, "chapter": chapter,
            "score": correct_count, "total": total, "passed": passed,
            "answers": details,
        })
        _save_user_results(user_data)

        self.set_header("Content-Type", "application/json")
        self.write({"score": correct_count, "total": total, "passed": passed, "attempt": attempt_num})


class DeleteAttemptHandler(HubOAuthenticated, web.RequestHandler):
    @web.authenticated
    def post(self):
        user = self.get_current_user()
        username = user.get("name", "Unknown")
        if username != ADMIN_USER:
            self.set_status(403)
            self.set_header("Content-Type", "application/json")
            self.write({"error": "Admins only"})
            return
        try:
            body = json.loads(self.request.body)
        except (json.JSONDecodeError, ValueError):
            self.set_status(400)
            self.set_header("Content-Type", "application/json")
            self.write({"error": "Invalid JSON"})
            return
        target_user = body.get("user", "").strip()
        target_attempt = body.get("attempt")
        if not target_user or target_attempt is None:
            self.set_status(400)
            self.set_header("Content-Type", "application/json")
            self.write({"error": "Missing user or attempt"})
            return
        try:
            target_attempt = int(target_attempt)
        except (ValueError, TypeError):
            self.set_status(400)
            self.set_header("Content-Type", "application/json")
            self.write({"error": "Invalid attempt number"})
            return
        user_data = _load_user_results(target_user)
        original_len = len(user_data["attempts"])
        user_data["attempts"] = [
            a for a in user_data["attempts"] if a.get("attempt") != target_attempt
        ]
        if len(user_data["attempts"]) == original_len:
            self.set_status(404)
            self.set_header("Content-Type", "application/json")
            self.write({"error": "Attempt not found"})
            return
        _save_user_results(user_data)
        self.set_header("Content-Type", "application/json")
        self.write({"ok": True})


class ResultsHandler(HubOAuthenticated, web.RequestHandler):
    @web.authenticated
    def get(self):
        user = self.get_current_user()
        username = user.get("name", "Unknown")
        prefix = os.environ.get("JUPYTERHUB_SERVICE_PREFIX", "/")
        if username != ADMIN_USER:
            self.set_status(403)
            self.set_header("Content-Type", "text/html; charset=utf-8")
            self.write("<h1 style='font-family:sans-serif;padding:2rem'>403 Forbidden</h1>"
                       "<p style='font-family:sans-serif;padding:0 2rem'>Admins only.</p>")
            return
        selected_user = self.get_argument("user", "").strip()
        users     = _list_result_users()
        user_data = _load_user_results(selected_user) if selected_user else None
        self.set_header("Content-Type", "text/html; charset=utf-8")
        self.write(_render_results_page(username, prefix, users, selected_user, user_data))


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def main():
    prefix = os.environ.get("JUPYTERHUB_SERVICE_PREFIX", "/")
    port   = int(os.environ.get("JUPYTERHUB_SERVICE_PORT", 10101))
    app = web.Application(
        [
            (prefix,                              QuizHandler),
            (prefix.rstrip("/") + "/submit",      SubmitHandler),
            (prefix.rstrip("/") + "/results",        ResultsHandler),
            (prefix.rstrip("/") + "/delete_attempt",  DeleteAttemptHandler),
            (prefix.rstrip("/") + "/oauth_callback",   HubOAuthCallbackHandler),
        ],
        cookie_secret=os.urandom(32),
        xsrf_cookies=False,
        # HubOAuth 5.x runs its own XSRF check inside _get_user_cookie for every
        # cookie-authenticated POST. Our fetch() calls don't carry an X-Xsrftoken
        # header, so the check silently returns None → @web.authenticated → 403.
        # Setting this flag skips that check (see HubOAuth.check_xsrf_cookie).
        disable_check_xsrf=True,
    )
    app.listen(port, "127.0.0.1")
    print(f"Quiz service listening on 127.0.0.1:{port}{prefix}", flush=True)
    ioloop.IOLoop.current().start()

if __name__ == "__main__":
    main()
