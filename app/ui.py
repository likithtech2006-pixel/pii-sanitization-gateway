"""Presentation layer for the Streamlit app: styles, motion and HTML components.

Everything is inline (no web fonts, no CDNs). Every value that comes from a document is HTML-escaped
before it is rendered.

The design follows Streamlit's own light/dark setting (menu > Settings > Theme): a small script reads
the active theme and sets <html data-lux-theme="light|dark">, and all colours are tokens for both modes.
The left sidebar (navigation, active document, system & settings) has its own compact styles (sb-*).
"""
import html
import json
import re
import urllib.parse
from typing import Dict, Iterable, List, Optional

import streamlit as st

# ------------------------------------------------------------------ icons
# st.html strips <svg>, so icons are CSS masks generated from these paths; they follow currentColor.
_ICONS = {
    "file": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
    "scan": '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/>'
            '<path d="M7 21H5a2 2 0 0 1-2-2v-2"/><path d="M7 12h10"/>',
    "redact": '<path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/><path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 '
              '13.16 0 0 1-1.67 2.68"/><path d="M6.61 6.61A13.53 13.53 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/>'
              '<path d="M2 2l20 20"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
    "send": '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
    "lock": '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "chip": '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/>'
            '<path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"/>',
    "pin": '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/>',
    "eyeoff": '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>'
              '<path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><path d="M1 1l22 22"/>',
    "alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>'
             '<path d="M12 9v4"/><path d="M12 17h.01"/>',
    "inbox": '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6'
             'l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
}


def icon(name: str, size: int = 18) -> str:
    return f'<i class="lux-ico lux-i-{name}" style="--s:{size}px" aria-hidden="true"></i>'


def _icon_css() -> str:
    rules = [".lux-ico{display:inline-block;flex:none;width:var(--s,18px);height:var(--s,18px);background:currentColor;"
             "-webkit-mask:var(--m) center/contain no-repeat;mask:var(--m) center/contain no-repeat;vertical-align:-.18em}"]
    for name, paths in _ICONS.items():
        svg = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='1.8' "
               f"stroke-linecap='round' stroke-linejoin='round'>{paths}</svg>")
        rules.append(f'.lux-i-{name}{{--m:url("data:image/svg+xml,{urllib.parse.quote(svg)}")}}')
    return "\n".join(rules)


def _e(value) -> str:
    return html.escape(str(value), quote=True)


# ------------------------------------------------------------------ design tokens (light default, dark override)
_TOKENS = r"""
:root{
  --lux-bg:#F5F7FB; --lux-glow-1:rgba(243,111,33,.11); --lux-glow-2:rgba(47,111,235,.09); --lux-glow-3:rgba(124,92,255,.06);
  --lux-panel:rgba(255,255,255,.74); --lux-surface:#FFFFFF; --lux-surface-2:rgba(248,250,253,.95);
  --lux-line:rgba(11,31,58,.08); --lux-line-2:rgba(11,31,58,.16);
  --lux-text:#0B1F3A; --lux-muted:#55657D; --lux-dim:#8794A8; --lux-strong:#0B1F3A;
  --lux-orange:#F36F21; --lux-amber:#DD6B12; --lux-green:#0E9F6E; --lux-red:#E5484D; --lux-blue:#2F6FEB;
  --lux-violet:#7C5CFF; --lux-yellow:#B7791F; --lux-teal:#0E9AA0;
  --lux-shadow:0 1px 2px rgba(11,31,58,.04),0 14px 34px -14px rgba(11,31,58,.16);
  --lux-shadow-hover:0 34px 70px -30px rgba(11,31,58,.32),0 0 44px -18px rgba(243,111,33,.38);
  --lux-header:rgba(255,255,255,.74);
  --lux-h1:linear-gradient(100deg,#0B1F3A 18%,#2F4C7A 32%,#F36F21 46%,#0B1F3A 62%);
  --lux-sheet-2:#E4EAF3; --lux-sheet-3:#D4DDEA;
  --lux-float-bg:rgba(255,255,255,.92); --lux-splash:#F5F7FB; --lux-grid:rgba(11,31,58,.045);
  --lux-cursor:radial-gradient(circle,rgba(243,111,33,.10),rgba(47,111,235,.05) 40%,transparent 68%); --lux-blend:normal;
  --lux-net-line:47,111,235; --lux-net-alpha:.16; --lux-net-dot:rgba(11,31,58,.32);
  /* sidebar */
  --sb-bg:#FFFFFF; --sb-hover:#F1F3F6; --sb-line:#E2E6EC; --sb-text:#0F1B2D; --sb-muted:#566275; --sb-dim:#7D8797;
  --sb-accent:#C9581A; --sb-accent-soft:rgba(201,88,26,.09); --sb-mark-bg:#0B1F3A; --sb-mark-fg:#FFFFFF; --sb-bad:#B42318;
}
:root[data-lux-theme="dark"]{
  --lux-bg:#060D1A; --lux-glow-1:rgba(243,111,33,.17); --lux-glow-2:rgba(91,157,255,.12); --lux-glow-3:rgba(168,139,255,.07);
  --lux-panel:rgba(15,31,56,.62); --lux-surface:#0B1830; --lux-surface-2:rgba(8,18,36,.94);
  --lux-line:rgba(150,175,215,.13); --lux-line-2:rgba(150,175,215,.26);
  --lux-text:#E7EDF6; --lux-muted:#8FA0BA; --lux-dim:#5F7190; --lux-strong:#FFFFFF;
  --lux-amber:#FFB067; --lux-green:#2ED19A; --lux-red:#FF5E62; --lux-blue:#5B9DFF;
  --lux-violet:#A88BFF; --lux-yellow:#F5C451; --lux-teal:#3DD6D0;
  --lux-shadow:0 18px 40px -24px rgba(0,0,0,.8);
  --lux-shadow-hover:0 34px 70px -30px rgba(0,0,0,.95),0 0 44px -18px rgba(243,111,33,.5);
  --lux-header:rgba(6,13,26,.62);
  --lux-h1:linear-gradient(100deg,#FFFFFF 18%,#FFD2B0 34%,#F36F21 46%,#FFFFFF 62%);
  --lux-sheet-2:rgba(24,46,80,.75); --lux-sheet-3:rgba(30,56,96,.55);
  --lux-float-bg:rgba(8,18,36,.85); --lux-splash:#050B16; --lux-grid:rgba(150,175,215,.05);
  --lux-cursor:radial-gradient(circle,rgba(243,111,33,.14),rgba(91,157,255,.06) 40%,transparent 68%); --lux-blend:screen;
  --lux-net-line:120,160,230; --lux-net-alpha:.2; --lux-net-dot:rgba(170,195,240,.55);
  --sb-bg:#111A2B; --sb-hover:#16213A; --sb-line:#243049; --sb-text:#E6EBF2; --sb-muted:#9AA6B8; --sb-dim:#7B879B;
  --sb-accent:#F08A4B; --sb-accent-soft:rgba(240,138,75,.12); --sb-mark-bg:#F08A4B; --sb-mark-fg:#111A2B; --sb-bad:#F47C70;
}
:root{--lux-ease:cubic-bezier(.22,1,.36,1);
  --lux-font:-apple-system,BlinkMacSystemFont,"SF Pro Text","Inter","Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --lux-mono:"SF Mono",ui-monospace,Menlo,Consolas,"Liberation Mono",monospace}
@property --lux-angle{syntax:'<angle>';initial-value:0deg;inherits:false}
@property --lux-num{syntax:'<integer>';initial-value:0;inherits:false}
"""

_CSS = r"""
/* ---------- canvas */
html,body,[data-testid="stApp"]{font-family:var(--lux-font)}
html,body{background:
    radial-gradient(1100px 620px at 88% -12%,var(--lux-glow-1),transparent 62%),
    radial-gradient(900px 560px at -12% 18%,var(--lux-glow-2),transparent 60%),
    var(--lux-bg)!important;background-attachment:fixed!important;transition:background-color .5s}
[data-testid="stApp"]{background:transparent!important;position:relative;z-index:1}
[data-testid="stApp"]::before{content:"";position:fixed;inset:-20%;pointer-events:none;z-index:0;
  background:radial-gradient(38% 30% at 30% 30%,var(--lux-glow-1),transparent 70%),
             radial-gradient(30% 26% at 70% 60%,var(--lux-glow-2),transparent 70%),
             radial-gradient(26% 22% at 50% 90%,var(--lux-glow-3),transparent 70%);
  filter:blur(40px);animation:lux-aurora 26s ease-in-out infinite alternate;will-change:transform}
[data-testid="stApp"]::after{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
  background-image:linear-gradient(var(--lux-grid) 1px,transparent 1px),linear-gradient(90deg,var(--lux-grid) 1px,transparent 1px);
  background-size:56px 56px;-webkit-mask-image:radial-gradient(ellipse 70% 60% at 50% 20%,#000 30%,transparent 80%);
  mask-image:radial-gradient(ellipse 70% 60% at 50% 20%,#000 30%,transparent 80%)}
@keyframes lux-aurora{0%{transform:translate3d(0,0,0) rotate(0)}50%{transform:translate3d(4%,-3%,0) rotate(8deg)}
  100%{transform:translate3d(-3%,4%,0) rotate(-6deg)}}
[data-testid="stAppViewContainer"],[data-testid="stMain"]{background:transparent!important;position:relative;z-index:1}
[data-testid="stMainBlockContainer"]{max-width:1180px;padding-top:2.4rem;padding-bottom:5rem}
#lux-net{position:fixed;inset:0;z-index:0;pointer-events:none}
#lux-glow{position:fixed;left:0;top:0;width:640px;height:640px;margin:-320px 0 0 -320px;border-radius:50%;z-index:2;
  pointer-events:none;background:var(--lux-cursor);mix-blend-mode:var(--lux-blend);opacity:0;transition:opacity .6s}
body.lux-pointer #lux-glow{opacity:1}

/* ---------- chrome (menu and Deploy stay as in stock Streamlit) */
[data-testid="stHeader"]{background:transparent!important;transition:background .4s var(--lux-ease)}
[data-testid="stHeader"].lux-scrolled{background:var(--lux-header)!important;backdrop-filter:blur(14px) saturate(150%);
  -webkit-backdrop-filter:blur(14px) saturate(150%);border-bottom:1px solid var(--lux-line)}
.lux-progress{position:fixed;top:0;left:0;right:0;height:3px;z-index:1000001;transform-origin:0 50%;transform:scaleX(0);
  background:linear-gradient(90deg,var(--lux-orange),#FFB067,var(--lux-blue));box-shadow:0 0 12px rgba(243,111,33,.6);pointer-events:none}
[data-testid="stMain"]{scrollbar-width:thin;scrollbar-color:var(--lux-line-2) transparent}

/* ---------- sidebar: compact navigation */
[data-testid="stSidebar"]{background:var(--sb-bg)!important;border-right:1px solid var(--sb-line)}
.sb-brand{display:flex;align-items:center;gap:.6rem;padding:.1rem 0 .9rem;margin-bottom:.2rem;border-bottom:1px solid var(--sb-line)}
.sb-mark{width:30px;height:30px;border-radius:8px;display:grid;place-items:center;color:var(--sb-mark-fg);background:var(--sb-mark-bg);flex:none}
.sb-brand b{display:block;font-size:.98rem;color:var(--sb-text);letter-spacing:-.005em;line-height:1.2}
.sb-brand small{display:block;font-size:.76rem;color:var(--sb-muted)}
.sb-label{font-size:.68rem;font-weight:650;letter-spacing:.09em;text-transform:uppercase;color:var(--sb-dim);margin:.8rem 0 .3rem}
.st-key-nav,.st-key-nav [data-testid="stRadio"],.st-key-nav [data-testid="stRadio"] > div{width:100%!important}
.st-key-nav [role="radiogroup"]{gap:2px;width:100%;align-items:stretch}
.st-key-nav [role="radiogroup"] > div{width:100%;display:block}
.st-key-nav [data-testid="stRadioOption"]{margin:0!important;padding:.45rem .6rem;border-radius:6px;width:100%;display:flex;box-sizing:border-box;
  cursor:pointer;position:relative;transition:background-color .12s ease}
.st-key-nav [data-testid="stRadioOption"] > div > div:first-child{display:none}
.st-key-nav [data-testid="stRadioOption"] p{font-size:.9rem;font-weight:550;color:var(--sb-muted)}
.st-key-nav [data-testid="stRadioOption"] p span[role="img"]{margin-right:.15rem}
.st-key-nav [data-testid="stRadioOption"]:hover{background:var(--sb-hover)}
.st-key-nav [data-testid="stRadioOption"]:hover p{color:var(--sb-text)}
.st-key-nav [data-testid="stRadioOption"][data-selected="true"]{background:var(--sb-accent-soft)}
.st-key-nav [data-testid="stRadioOption"][data-selected="true"] p{color:var(--sb-accent);font-weight:650}
.st-key-nav [data-testid="stRadioOption"][data-selected="true"]::before{content:"";position:absolute;left:0;top:9px;bottom:9px;
  width:3px;border-radius:3px;background:var(--sb-accent)}
.st-key-nav [data-testid="stRadioOption"]:has(input:focus-visible){outline:2px solid var(--sb-accent);outline-offset:1px}
.sb-engine{display:flex;justify-content:space-between;gap:.6rem;padding:.32rem 0;font-size:.8rem;border-bottom:1px solid var(--sb-line)}
.sb-engine:last-child{border-bottom:none}
.sb-engine span{color:var(--sb-muted);flex:none}
.sb-engine b{font-weight:600;color:var(--sb-text);text-align:right;overflow-wrap:anywhere}
.sb-engine b.bad{color:var(--sb-bad)}

/* ---------- hero */
.lux-hero{display:grid;grid-template-columns:1.2fr .95fr;gap:2.4rem;align-items:center;margin:.2rem 0 .6rem}
.lux-eyebrow{display:inline-flex;align-items:center;gap:.5rem;padding:.4rem .85rem;border-radius:999px;font-size:.72rem;
  font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--lux-amber);
  background:color-mix(in srgb,var(--lux-orange) 10%,transparent);border:1px solid color-mix(in srgb,var(--lux-orange) 30%,transparent)}
.lux-eyebrow i{width:7px;height:7px;border-radius:50%;background:var(--lux-orange);box-shadow:0 0 10px var(--lux-orange);
  animation:lux-breathe 2s ease-in-out infinite}
@keyframes lux-breathe{50%{box-shadow:0 0 22px var(--lux-orange)}}
.lux-h1{font-size:clamp(2.5rem,5.4vw,4.2rem);line-height:1.02;letter-spacing:-.04em;font-weight:850;margin:1rem 0 .9rem;
  background:var(--lux-h1);background-size:260% 100%;-webkit-background-clip:text;background-clip:text;color:transparent;
  animation:lux-shimmer 9s linear infinite}
@keyframes lux-shimmer{0%{background-position:100% 0}100%{background-position:-160% 0}}
.lux-lead{font-size:1.08rem;line-height:1.7;color:var(--lux-muted);max-width:40rem}
.lux-lead b{color:var(--lux-strong)}
.lux-lead code{font-family:var(--lux-mono);font-size:.86em;color:var(--lux-amber);
  background:color-mix(in srgb,var(--lux-orange) 10%,transparent);padding:.1em .4em;border-radius:6px}
.lux-chips{display:flex;flex-wrap:wrap;gap:.55rem;margin-top:1.4rem}
.lux-chip{display:inline-flex;align-items:center;gap:.45rem;padding:.5rem .9rem;border-radius:999px;font-size:.82rem;
  color:var(--lux-text);background:var(--lux-panel);border:1px solid var(--lux-line);backdrop-filter:blur(10px);
  box-shadow:var(--lux-shadow);transition:transform .45s var(--lux-ease),border-color .45s,box-shadow .45s}
.lux-chip .lux-ico{color:var(--lux-orange)}
.lux-chip:hover{transform:translateY(-4px) scale(1.03);border-color:color-mix(in srgb,var(--lux-orange) 50%,transparent);
  box-shadow:0 14px 30px -14px rgba(243,111,33,.6)}
.lux-cta{display:flex;align-items:center;gap:.6rem;margin-top:1.7rem;font-size:.85rem;color:var(--lux-muted)}
.lux-mouse{width:22px;height:34px;border-radius:12px;border:2px solid var(--lux-line-2);position:relative}
.lux-mouse::after{content:"";position:absolute;left:50%;top:6px;width:4px;height:7px;margin-left:-2px;border-radius:2px;
  background:var(--lux-orange);animation:lux-wheel 1.8s ease-in-out infinite}
@keyframes lux-wheel{0%{opacity:0;translate:0 0}30%{opacity:1}100%{opacity:0;translate:0 12px}}
.lux-hero-copy{animation:lux-in 1s var(--lux-ease) both}
.lux-hero-art{position:relative;height:380px;perspective:1100px;animation:lux-in 1.1s .15s var(--lux-ease) both}
.lux-tilt{position:absolute;inset:0;transform-style:preserve-3d;transition:transform .6s var(--lux-ease);
  transform:rotateX(var(--rx,0deg)) rotateY(var(--ry,0deg))}
.lux-orbit{position:absolute;border-radius:50%;border:1px dashed var(--lux-line-2);pointer-events:none}
.lux-orbit.o1{width:430px;height:430px;right:-50px;top:-30px;animation:lux-rot 40s linear infinite}
.lux-orbit.o2{width:310px;height:310px;right:12px;top:30px;border-color:color-mix(in srgb,var(--lux-orange) 35%,transparent);
  animation:lux-rot 26s linear infinite reverse}
.lux-orbit .sat{position:absolute;top:-5px;left:50%;width:10px;height:10px;border-radius:50%;background:var(--lux-orange);
  box-shadow:0 0 16px var(--lux-orange)}
.lux-orbit.o1 .sat{background:var(--lux-blue);box-shadow:0 0 16px var(--lux-blue)}
@keyframes lux-rot{to{rotate:360deg}}
.lux-sheet{position:absolute;width:250px;height:310px;border-radius:18px;border:1px solid var(--lux-line-2)}
.lux-sheet.s3{right:6px;top:14px;background:var(--lux-sheet-3);transform:translateZ(-60px)}
.lux-sheet.s2{right:34px;top:32px;background:var(--lux-sheet-2);transform:translateZ(-30px)}
.lux-sheet.s1{right:62px;top:50px;background:linear-gradient(180deg,#FFFFFF,#EEF2F8);border:1px solid rgba(11,31,58,.08);overflow:hidden;
  box-shadow:0 40px 80px -30px rgba(11,31,58,.45),0 0 0 1px rgba(255,255,255,.06)}
.lux-ln{position:absolute;left:22px;height:10px;border-radius:6px;background:#CBD5E2}
.lux-tg{position:absolute;height:20px;padding:0 9px;border-radius:999px;font:700 10.5px/20px var(--lux-mono);color:#fff;
  background:linear-gradient(135deg,#F36F21,#D9520E);box-shadow:0 6px 16px -6px rgba(243,111,33,.9);
  opacity:0;scale:.6;animation:lux-tag 6s var(--lux-ease) infinite}
@keyframes lux-tag{0%,12%{opacity:0;scale:.6}18%,82%{opacity:1;scale:1}92%,100%{opacity:0;scale:.9}}
.lux-hide{position:absolute;height:12px;border-radius:6px;background:#9FB0C6;animation:lux-hide 6s var(--lux-ease) infinite}
@keyframes lux-hide{0%,12%{opacity:1}18%,82%{opacity:0}92%,100%{opacity:1}}
.lux-beam{position:absolute;left:-10%;right:-10%;height:46px;top:-60px;
  background:linear-gradient(180deg,transparent,rgba(243,111,33,.18) 60%,rgba(243,111,33,.8) 96%,transparent);
  animation:lux-beam 6s cubic-bezier(.45,0,.25,1) infinite}
@keyframes lux-beam{0%{translate:0 0}70%,100%{translate:0 400px}}
.lux-badge{position:absolute;right:16px;bottom:0;width:88px;height:88px;border-radius:50%;display:grid;place-items:center;
  color:#fff;background:radial-gradient(circle at 30% 30%,#FF8A45,#F36F21 55%,#B9440A);transform:translateZ(70px);
  box-shadow:0 20px 50px -14px rgba(243,111,33,.9),inset 0 2px 0 rgba(255,255,255,.35)}
.lux-badge::before,.lux-badge::after{content:"";position:absolute;inset:0;border-radius:50%;border:2px solid rgba(243,111,33,.55);
  animation:lux-ripple 3s var(--lux-ease) infinite}
.lux-badge::after{animation-delay:1.5s}
@keyframes lux-ripple{0%{scale:1;opacity:.8}100%{scale:1.9;opacity:0}}
.lux-float{position:absolute;padding:.35rem .7rem;border-radius:999px;font:700 .72rem var(--lux-mono);color:var(--c);
  background:var(--lux-float-bg);border:1px solid color-mix(in srgb,var(--c) 45%,transparent);backdrop-filter:blur(8px);
  box-shadow:0 10px 30px -10px color-mix(in srgb,var(--c) 70%,transparent);animation:lux-bob 5s ease-in-out infinite;
  animation-delay:var(--d,0s);transform:translateZ(90px)}
@keyframes lux-bob{0%,100%{translate:0 0}50%{translate:0 -14px}}

/* ---------- ticker */
.lux-ticker{position:relative;overflow:hidden;margin:1.4rem 0 1.6rem;padding:.3rem 0;
  -webkit-mask-image:linear-gradient(90deg,transparent,#000 10%,#000 90%,transparent);
          mask-image:linear-gradient(90deg,transparent,#000 10%,#000 90%,transparent)}
.lux-row{display:flex;gap:.8rem;width:max-content;animation:lux-marquee 40s linear infinite;padding:.35rem 0}
.lux-row.rev{animation-direction:reverse;animation-duration:48s}
.lux-ticker:hover .lux-row{animation-play-state:paused}
@keyframes lux-marquee{to{translate:-50% 0}}
.lux-tick{display:inline-flex;align-items:center;gap:.55rem;padding:.5rem .9rem;border-radius:12px;white-space:nowrap;
  font:700 .8rem var(--lux-mono);color:var(--c);background:color-mix(in srgb,var(--c) 8%,var(--lux-surface));
  border:1px solid color-mix(in srgb,var(--c) 28%,transparent);transition:transform .4s var(--lux-ease),box-shadow .4s}
.lux-tick:hover{transform:translateY(-4px) scale(1.06);box-shadow:0 12px 30px -12px var(--c)}
.lux-tick s{color:var(--lux-dim);font-weight:500}

/* ---------- sections + cards */
.lux-section{margin:3rem 0 1.1rem}
.lux-section.top{margin-top:.4rem}
.lux-kicker{font-size:.72rem;font-weight:750;letter-spacing:.16em;text-transform:uppercase;color:var(--lux-orange)}
.lux-h2{font-size:clamp(1.6rem,3vw,2.2rem);font-weight:800;letter-spacing:-.03em;color:var(--lux-text);margin:.35rem 0 0}
.lux-sub{color:var(--lux-muted);margin:.4rem 0 0;font-size:.95rem}
.lux-label{font-size:.72rem;font-weight:750;letter-spacing:.16em;text-transform:uppercase;color:var(--lux-orange);margin:2rem 0 .7rem}
.lux-grid{display:grid;gap:1rem}
.lux-g5{grid-template-columns:repeat(5,minmax(0,1fr))}
.lux-g6{grid-template-columns:repeat(6,minmax(0,1fr))}
.lux-card{position:relative;padding:1.15rem 1.1rem;border-radius:20px;background:var(--lux-panel);border:1px solid var(--lux-line);
  backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);overflow:hidden;isolation:isolate;box-shadow:var(--lux-shadow);
  transition:transform .6s var(--lux-ease),border-color .5s var(--lux-ease),box-shadow .5s var(--lux-ease)}
.lux-card:hover{border-color:var(--lux-line-2);box-shadow:var(--lux-shadow-hover)}
.lux-spot::before{content:"";position:absolute;inset:0;z-index:-1;opacity:0;transition:opacity .45s;
  background:radial-gradient(380px circle at var(--mx,50%) var(--my,50%),rgba(243,111,33,.14),transparent 45%)}
.lux-spot::after{content:"";position:absolute;inset:0;border-radius:inherit;padding:1px;opacity:0;transition:opacity .45s;pointer-events:none;
  background:radial-gradient(240px circle at var(--mx,50%) var(--my,50%),rgba(243,111,33,.85),transparent 60%);
  -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;
          mask:linear-gradient(#000 0 0) content-box exclude,linear-gradient(#000 0 0)}
.lux-spot:hover::before,.lux-spot:hover::after{opacity:1}
.lux-tiltcard{transform:perspective(900px) rotateX(var(--rx,0deg)) rotateY(var(--ry,0deg));will-change:transform}
.lux-tiltcard:hover{transform:perspective(900px) rotateX(var(--rx,0deg)) rotateY(var(--ry,0deg)) translateY(-8px) scale(1.02);
  transition:transform .15s linear,border-color .5s,box-shadow .5s}
.lux-glare{position:absolute;inset:0;border-radius:inherit;pointer-events:none;z-index:2;opacity:0;transition:opacity .4s;
  background:linear-gradient(115deg,transparent 30%,rgba(255,255,255,.35) 48%,transparent 62%);background-size:250% 250%;
  background-position:var(--gx,50%) var(--gy,50%);mix-blend-mode:soft-light}
.lux-tiltcard:hover .lux-glare{opacity:1}
.lux-step .n{font:700 .72rem var(--lux-mono);color:var(--lux-dim);letter-spacing:.08em}
.lux-step .ic{position:relative;width:48px;height:48px;border-radius:14px;display:grid;place-items:center;margin:.7rem 0 .8rem;
  color:var(--lux-orange);background:var(--lux-surface);border:1px solid color-mix(in srgb,var(--lux-orange) 28%,transparent);
  box-shadow:0 8px 20px -10px rgba(243,111,33,.5);transition:transform .6s var(--lux-ease),background .4s,color .4s}
.lux-step:hover .ic{transform:rotate(-10deg) scale(1.15);background:var(--lux-orange);color:#fff}
.lux-step b{display:block;color:var(--lux-text);font-size:1.02rem;margin-bottom:.3rem}
.lux-step p{color:var(--lux-muted);font-size:.84rem;line-height:1.5;margin:0}
.lux-flow{position:relative}
.lux-flow::after{content:"";position:absolute;left:5%;right:5%;top:84px;height:2px;z-index:0;background:var(--lux-line)}
.lux-flow::before{content:"";position:absolute;left:5%;right:5%;top:84px;height:2px;border-radius:2px;z-index:1;
  background:linear-gradient(90deg,var(--lux-orange),#FFB067,var(--lux-blue));box-shadow:0 0 18px rgba(243,111,33,.7);
  transform-origin:0 50%}
.lux-flow .lux-card{z-index:2}
.lux-note{margin-top:1.2rem;color:var(--lux-muted);font-size:.88rem}
.lux-note code{font-family:var(--lux-mono);color:var(--lux-amber)}

/* stats */
.lux-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1rem}
.lux-stat{padding:1.5rem 1.35rem}
.lux-stat .num{font-size:clamp(2.4rem,4.4vw,3.4rem);font-weight:850;letter-spacing:-.045em;line-height:1;color:var(--c)}
.lux-stat .cap{margin-top:.7rem;color:var(--lux-muted);font-size:.85rem;line-height:1.45}
.lux-stat .cap b{display:block;color:var(--lux-text);font-size:.96rem;margin-bottom:.15rem}

/* bento */
.lux-bento{display:grid;grid-template-columns:1.15fr 1fr 1fr;gap:1rem}
.lux-bento .lux-card{padding:1.45rem;min-height:260px}
.lux-bento h4{margin:0 0 .35rem!important;padding:0!important;font-size:1.08rem!important;color:var(--lux-text)}
.lux-bento p.d{margin:0 0 1.1rem;color:var(--lux-muted);font-size:.86rem;line-height:1.5}
.lux-map{display:grid;gap:.55rem}
.lux-map div{display:flex;align-items:center;gap:.6rem;font:.8rem var(--lux-mono);color:var(--lux-muted)}
.lux-map s{color:var(--lux-text);text-decoration:none;min-width:150px}
.lux-map em{flex:1;height:2px;border-radius:2px;background:var(--lux-line-2);position:relative;overflow:hidden}
.lux-map em::after{content:"";position:absolute;top:0;left:-30%;width:30%;height:2px;border-radius:2px;
  background:var(--lux-orange);box-shadow:0 0 10px var(--lux-orange);animation:lux-zip 2.4s ease-in-out infinite;
  animation-delay:calc(var(--i)*.3s)}
@keyframes lux-zip{to{left:110%}}
.lux-map b{color:var(--lux-orange);font-weight:800}
.lux-lanes{position:relative;height:124px;margin-top:.4rem}
.lux-lane{position:absolute;left:0;right:0;height:2px;background:var(--lux-line-2)}
.lux-lane.a{top:30px}.lux-lane.b{top:94px}
.lux-gate{position:absolute;left:55%;top:6px;bottom:6px;width:5px;border-radius:5px;
  background:linear-gradient(var(--lux-orange),#FFB067);box-shadow:0 0 20px var(--lux-orange)}
.lux-pkt{position:absolute;width:12px;height:12px;margin-top:-5px;border-radius:50%;left:0}
.lux-lane.a .lux-pkt{background:var(--lux-green);box-shadow:0 0 12px var(--lux-green);animation:lux-pass 3s linear infinite;animation-delay:var(--d)}
.lux-lane.b .lux-pkt{background:var(--lux-red);box-shadow:0 0 12px var(--lux-red);animation:lux-stop 3s linear infinite;animation-delay:var(--d)}
@keyframes lux-pass{0%{left:0;opacity:0}10%{opacity:1}90%{opacity:1}100%{left:100%;opacity:0}}
@keyframes lux-stop{0%{left:0;opacity:0}10%{opacity:1}50%{left:calc(55% - 14px);opacity:1;scale:1}60%,100%{left:calc(55% - 14px);opacity:0;scale:2.2}}
.lux-lbl{position:absolute;left:0;font:700 .68rem var(--lux-mono);letter-spacing:.1em}
.lux-lbl.a{top:6px;color:var(--lux-green)}.lux-lbl.b{top:104px;color:var(--lux-red)}
.lux-path{display:grid;grid-template-columns:minmax(0,1fr);gap:.55rem}
.lux-path span{display:inline-flex;align-items:center;gap:.45rem;padding:.45rem .7rem;border-radius:10px;width:fit-content;max-width:100%;
  font:.78rem var(--lux-mono);color:var(--lux-text);background:var(--lux-surface);border:1px solid var(--lux-line);
  overflow-wrap:anywhere;line-height:1.4;transition:transform .4s var(--lux-ease),border-color .4s}
.lux-path span:hover{transform:translateX(6px);border-color:color-mix(in srgb,var(--lux-orange) 50%,transparent)}
.lux-path .lux-ico{color:var(--lux-orange)}

/* ---------- uploader */
[data-testid="stFileUploader"] label p{font-size:.72rem!important;font-weight:750;letter-spacing:.16em;text-transform:uppercase;
  color:var(--lux-orange)!important}
[data-testid="stFileUploaderDropzone"]{position:relative;border-radius:22px!important;border:1px solid var(--lux-line-2)!important;
  background:var(--lux-panel)!important;backdrop-filter:blur(16px);padding:1.5rem!important;overflow:hidden;box-shadow:var(--lux-shadow);
  transition:transform .5s var(--lux-ease),box-shadow .5s var(--lux-ease),border-color .5s}
[data-testid="stFileUploaderDropzone"]::before{content:"";position:absolute;inset:0;border-radius:inherit;padding:1.5px;pointer-events:none;
  background:conic-gradient(from var(--lux-angle),transparent 0 68%,#F36F21 80%,#FFB067 87%,transparent 95%);
  -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;
          mask:linear-gradient(#000 0 0) content-box exclude,linear-gradient(#000 0 0);animation:lux-spin 5s linear infinite}
@keyframes lux-spin{to{--lux-angle:360deg}}
[data-testid="stFileUploaderDropzone"]:hover{transform:translateY(-3px);border-color:color-mix(in srgb,var(--lux-orange) 50%,transparent)!important;
  box-shadow:0 0 0 5px rgba(243,111,33,.08),0 28px 60px -26px rgba(243,111,33,.5)}

/* ---------- buttons (magnetic: translate is set from the script) */
[data-testid="stMain"] [data-testid="stBaseButton-secondary"],[data-testid="stMain"] [data-testid="stBaseButton-primary"]{
  position:relative;overflow:hidden;border-radius:12px!important;font-weight:650!important;
  border:1px solid color-mix(in srgb,var(--lux-orange) 45%,transparent)!important;
  background:color-mix(in srgb,var(--lux-orange) 9%,var(--lux-surface))!important;color:var(--lux-text)!important;
  transition:translate .35s var(--lux-ease),transform .45s var(--lux-ease),box-shadow .45s,background .45s,color .3s!important}
[data-testid="stMain"] [data-testid="stBaseButton-secondary"]::after,[data-testid="stMain"] [data-testid="stBaseButton-primary"]::after{
  content:"";position:absolute;top:0;bottom:0;width:40%;left:-60%;transform:skewX(-20deg);
  background:linear-gradient(90deg,transparent,rgba(255,255,255,.45),transparent);transition:left .8s var(--lux-ease)}
[data-testid="stMain"] [data-testid="stBaseButton-secondary"]:hover:not(:disabled),
[data-testid="stMain"] [data-testid="stBaseButton-primary"]:hover:not(:disabled){
  background:linear-gradient(135deg,#F36F21,#D4520D)!important;color:#fff!important;box-shadow:0 16px 34px -14px rgba(243,111,33,.85)}
[data-testid="stMain"] [data-testid="stBaseButton-secondary"]:hover::after{left:130%}
[data-testid="stMain"] [data-testid^="stBaseButton"]:hover:not(:disabled) p{color:#fff!important}
[data-testid="stMain"] [data-testid="stBaseButton-primary"]{background:linear-gradient(135deg,#F36F21,#D4520D)!important;color:#fff!important}
[data-testid="stMain"] [data-testid="stBaseButton-primary"] p{color:#fff!important}
[data-testid="stMain"] [data-testid^="stBaseButton"]:disabled{opacity:.45}
[data-testid="stFileUploaderDropzone"] [data-testid="stBaseButton-secondary"]{border-radius:999px!important}

/* ---------- document result */
.lux-doc{display:flex;align-items:center;gap:1.1rem;padding:1.35rem 1.45rem;margin-top:1rem}
.lux-ring{position:absolute;inset:0;border-radius:inherit;padding:1.5px;pointer-events:none;z-index:1;
  background:conic-gradient(from var(--lux-angle),transparent 0 60%,var(--rc) 78%,transparent 92%);
  -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;
          mask:linear-gradient(#000 0 0) content-box exclude,linear-gradient(#000 0 0);animation:lux-spin 4s linear infinite}
.lux-doc.blocked{animation:lux-alarm 2.4s ease-in-out infinite}
@keyframes lux-alarm{50%{box-shadow:0 0 0 1px color-mix(in srgb,var(--lux-red) 45%,transparent),0 0 70px -16px var(--lux-red)}}
.lux-ftype{width:56px;height:64px;border-radius:12px;flex:none;display:grid;place-items:center;font:800 .78rem var(--lux-mono);
  color:#fff;background:linear-gradient(160deg,var(--c1),var(--c2));box-shadow:0 14px 30px -14px var(--c1)}
.lux-ftype.sm{width:38px;height:42px;border-radius:9px;font-size:.62rem}
.lux-doc h3{margin:0!important;padding:0!important;font-size:1.3rem!important;letter-spacing:-.01em;color:var(--lux-text);word-break:break-all}
.lux-doc .meta{display:flex;flex-wrap:wrap;gap:.45rem;margin-top:.45rem}
.lux-pill{display:inline-flex;align-items:center;gap:.4rem;padding:.25rem .65rem;border-radius:999px;font-size:.74rem;font-weight:650;
  color:var(--lux-muted);background:var(--lux-surface);border:1px solid var(--lux-line)}
.lux-status{margin-left:auto;display:flex;flex-direction:column;align-items:flex-end;gap:.35rem;text-align:right}
.lux-verdict{display:inline-flex;align-items:center;gap:.55rem;padding:.55rem 1.05rem;border-radius:999px;font-weight:850;
  letter-spacing:.12em;font-size:.88rem;color:var(--c);background:color-mix(in srgb,var(--c) 12%,var(--lux-surface));
  border:1px solid color-mix(in srgb,var(--c) 45%,transparent);box-shadow:0 0 30px -8px color-mix(in srgb,var(--c) 60%,transparent);
  animation:lux-pop .8s .2s var(--lux-ease) both}
.lux-verdict.sm{padding:.3rem .7rem;font-size:.74rem;letter-spacing:.1em;animation:none}
@keyframes lux-pop{0%{opacity:0;scale:.6}60%{scale:1.08}100%{opacity:1;scale:1}}
.lux-status small{color:var(--lux-muted);font-size:.8rem;max-width:22rem}
.lux-fix{margin-top:.8rem;padding:.75rem .9rem;border-radius:12px;font-size:.88rem;color:var(--lux-text);
  background:color-mix(in srgb,var(--lux-red) 7%,var(--lux-surface));border:1px solid color-mix(in srgb,var(--lux-red) 25%,transparent)}
.lux-pipe{position:relative;display:grid;grid-template-columns:repeat(5,1fr);padding:1.55rem 1.2rem 1.25rem;margin-top:1rem}
.lux-track{position:absolute;left:10%;right:10%;top:3rem;height:3px;border-radius:3px;background:var(--lux-line)}
.lux-track i{position:absolute;inset:0 auto 0 0;width:var(--w);border-radius:3px;background:linear-gradient(90deg,var(--lux-green),var(--lux-teal));
  box-shadow:0 0 14px color-mix(in srgb,var(--lux-green) 70%,transparent);animation:lux-grow 1.8s .3s var(--lux-ease) both}
.lux-track.fail i{background:linear-gradient(90deg,var(--lux-green),var(--lux-red))}
.lux-track.ok i::after{content:"";position:absolute;top:-4px;width:46px;height:11px;border-radius:11px;
  background:radial-gradient(closest-side,#fff,transparent);animation:lux-packet 1.6s linear 2.2s infinite}
@keyframes lux-packet{from{left:0}to{left:calc(100% - 46px)}}
@keyframes lux-grow{from{width:0}}
.lux-node{position:relative;text-align:center;animation:lux-in .7s var(--lux-ease) both;animation-delay:calc(var(--i)*.28s + .2s)}
.lux-node .o{width:48px;height:48px;margin:0 auto .65rem;border-radius:50%;display:grid;place-items:center;
  color:var(--c);background:var(--lux-surface);border:2px solid var(--c);
  box-shadow:0 0 0 6px color-mix(in srgb,var(--c) 12%,transparent),0 0 24px -4px var(--c);transition:transform .5s var(--lux-ease)}
.lux-node:hover .o{transform:scale(1.15) rotate(-6deg)}
.lux-node.fail .o{animation:lux-shake .6s calc(var(--i)*.28s + .6s) both}
@keyframes lux-shake{0%,100%{translate:0 0}20%,60%{translate:-4px 0}40%,80%{translate:4px 0}}
.lux-node b{display:block;color:var(--lux-text);font-size:.92rem}
.lux-node span{display:block;color:var(--lux-muted);font-size:.76rem;margin-top:.15rem}
.lux-metric{padding:1rem 1.05rem}
.lux-metric .lbl{font-size:.68rem;font-weight:750;letter-spacing:.13em;text-transform:uppercase;color:var(--lux-muted)}
.lux-metric .val{font-size:2.3rem;font-weight:850;letter-spacing:-.03em;line-height:1.1;margin-top:.35rem;color:var(--c,var(--lux-text));
  font-variant-numeric:tabular-nums}
.lux-count{counter-reset:lux var(--lux-num);animation:lux-count 1.6s .35s var(--lux-ease) both}
.lux-count::after{content:counter(lux)}
@keyframes lux-count{from{--lux-num:0}to{--lux-num:var(--to)}}
.lux-sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.lux-warn{display:flex;gap:.6rem;align-items:flex-start;margin-top:1rem;padding:.8rem 1rem;border-radius:14px;font-size:.86rem;
  color:var(--lux-text);background:color-mix(in srgb,var(--lux-yellow) 10%,var(--lux-surface));
  border:1px solid color-mix(in srgb,var(--lux-yellow) 35%,transparent);overflow-wrap:anywhere}
.lux-warn .lux-ico{color:var(--lux-yellow);margin-top:.1rem}

/* session list, document context, empty states, compare, outputs */
.lux-drow{display:flex;align-items:center;gap:.7rem;flex-wrap:wrap;min-height:2.4rem}
.lux-drow .name{font-weight:700;color:var(--lux-text);overflow-wrap:anywhere}
.lux-drow .meta{color:var(--lux-muted);font-size:.84rem}
.lux-drow.active .name{color:var(--lux-orange)}
.lux-ctx{display:flex;align-items:center;gap:.8rem;flex-wrap:wrap;padding:.85rem 1.1rem;margin:0 0 1.2rem}
.lux-ctx .name{font-weight:700;color:var(--lux-text);overflow-wrap:anywhere}
.lux-ctx .meta{color:var(--lux-muted);font-size:.84rem}
.lux-empty{display:flex;gap:1.1rem;align-items:flex-start;padding:1.5rem 1.5rem}
.lux-empty .mk{width:48px;height:48px;border-radius:14px;display:grid;place-items:center;flex:none;color:var(--lux-orange);
  background:color-mix(in srgb,var(--lux-orange) 10%,var(--lux-surface));border:1px solid color-mix(in srgb,var(--lux-orange) 28%,transparent)}
.lux-empty.bad .mk{color:var(--lux-red);background:color-mix(in srgb,var(--lux-red) 10%,var(--lux-surface));
  border-color:color-mix(in srgb,var(--lux-red) 30%,transparent)}
.lux-empty b{display:block;color:var(--lux-text);font-size:1.05rem}
.lux-empty p{margin:.35rem 0 0;color:var(--lux-muted);font-size:.9rem;line-height:1.55}
.lux-cmp{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
.lux-cmp .lux-card{padding:0;min-width:0}
.lux-cmp .ch{padding:.7rem 1rem;font-size:.7rem;font-weight:750;letter-spacing:.14em;text-transform:uppercase;color:var(--lux-orange);
  border-bottom:1px solid var(--lux-line)}
.lux-cmp .lux-txt,.lux-cmp .hid{padding:.9rem 1rem}
.lux-cmp .hid{color:var(--lux-muted);font-size:.88rem;line-height:1.55}
.lux-out b{display:block;color:var(--lux-text);font-size:.95rem}
.lux-out span{display:block;color:var(--lux-muted);font-size:.84rem;margin-top:.15rem}
.lux-out span.na{color:var(--lux-dim)}

/* sanitized viewer */
.lux-viewer{max-height:560px;overflow:auto;border-radius:20px;background:var(--lux-surface);border:1px solid var(--lux-line);
  box-shadow:var(--lux-shadow);scrollbar-width:thin;scrollbar-color:var(--lux-line-2) transparent}
.lux-vhead{position:sticky;top:0;z-index:2;display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;padding:.8rem 1rem;
  background:var(--lux-surface-2);backdrop-filter:blur(10px);border-bottom:1px solid var(--lux-line);font-size:.8rem;color:var(--lux-muted)}
.lux-blk{padding:.75rem 1rem;border-bottom:1px solid var(--lux-line);transition:background .3s,padding-left .4s var(--lux-ease)}
.lux-blk:hover{background:color-mix(in srgb,var(--lux-orange) 4%,transparent);padding-left:1.3rem}
.lux-src{display:flex;align-items:center;gap:.35rem;font:600 .7rem var(--lux-mono);color:var(--lux-dim);margin-bottom:.3rem;overflow-wrap:anywhere}
.lux-txt{white-space:pre-wrap;font-size:.92rem;line-height:1.6;color:var(--lux-text);word-break:break-word}
.lux-tag{display:inline-block;padding:0 .45em;margin:0 .05em;border-radius:7px;font:700 .8em/1.65 var(--lux-mono);color:var(--c,var(--lux-orange));
  background:color-mix(in srgb,var(--c,var(--lux-orange)) 13%,transparent);border:1px solid color-mix(in srgb,var(--c,var(--lux-orange)) 40%,transparent);
  transition:transform .3s var(--lux-ease),box-shadow .3s,background .3s;cursor:default}
.lux-tag:hover,.lux-tag.lux-hl{transform:translateY(-1px) scale(1.07);background:color-mix(in srgb,var(--c,var(--lux-orange)) 26%,transparent);
  box-shadow:0 0 18px -4px var(--c,var(--lux-orange))}
.lux-bars{display:grid;gap:.75rem;padding:1.25rem 1.35rem;margin-bottom:1rem}
.lux-bar{display:grid;grid-template-columns:150px 1fr 48px;align-items:center;gap:.9rem}
.lux-bar .t{font:700 .78rem var(--lux-mono);color:var(--c)}
.lux-bar .r{height:10px;border-radius:10px;background:var(--lux-line);overflow:hidden}
.lux-bar .r i{display:block;height:100%;width:var(--w);border-radius:inherit;
  background:linear-gradient(90deg,color-mix(in srgb,var(--c) 50%,transparent),var(--c));box-shadow:0 0 14px -2px var(--c);
  animation:lux-grow 1.4s calc(var(--i)*.12s + .2s) var(--lux-ease) both}
.lux-bar .c{text-align:right;font-weight:800;color:var(--lux-text);font-variant-numeric:tabular-nums}

/* native widgets */
[data-testid="stDataFrame"],[data-testid="stCode"],[data-testid="stJson"]{border-radius:16px;overflow:hidden;border:1px solid var(--lux-line);
  box-shadow:var(--lux-shadow)}
[data-testid="stAlert"]{border-radius:16px}
[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"]{border-radius:20px}
.lux-foot{margin-top:4rem;padding-top:1.4rem;border-top:1px solid var(--lux-line);display:flex;justify-content:space-between;
  flex-wrap:wrap;gap:.6rem;color:var(--lux-dim);font-size:.8rem}

/* ---------- intro splash */
#lux-splash{position:fixed;inset:0;z-index:1000002;display:grid;place-items:center;background:var(--lux-splash);
  animation:lux-splash-out .9s 1.4s cubic-bezier(.7,0,.2,1) forwards}
#lux-splash .core{position:relative;width:120px;height:120px;display:grid;place-items:center;color:var(--lux-orange)}
#lux-splash .core::before,#lux-splash .core::after{content:"";position:absolute;inset:0;border-radius:50%;border:2px solid transparent;
  border-top-color:#F36F21;border-right-color:rgba(243,111,33,.3);animation:lux-rot 1s linear infinite}
#lux-splash .core::after{inset:14px;border-top-color:var(--lux-blue);border-right-color:color-mix(in srgb,var(--lux-blue) 30%,transparent);
  animation-duration:1.4s;animation-direction:reverse}
#lux-splash p{position:absolute;margin-top:190px;font:700 .72rem var(--lux-mono);letter-spacing:.32em;color:var(--lux-muted);
  text-transform:uppercase;animation:lux-blink 1s steps(2) infinite}
@keyframes lux-blink{50%{opacity:.35}}
@keyframes lux-splash-out{to{opacity:0;visibility:hidden;clip-path:circle(0% at 50% 50%)}}

/* ---------- entrance + scroll-driven effects (reveals use translate/scale so hover transforms still compose) */
@keyframes lux-in{from{opacity:0;translate:0 22px}to{opacity:1;translate:0 0}}
@keyframes lux-rise{from{opacity:0;translate:0 70px;scale:.93;filter:blur(8px)}to{opacity:1;translate:0 0;scale:1;filter:blur(0)}}
@keyframes lux-parallax{to{translate:0 -130px;scale:.9;opacity:.1}}
@keyframes lux-drift{to{translate:0 -60px;opacity:.2}}
@keyframes lux-beamfill{from{scale:0 1}to{scale:1 1}}
@keyframes lux-wipe{from{clip-path:inset(0 100% 0 0)}to{clip-path:inset(0 0 0 0)}}
@keyframes lux-tagin{from{filter:blur(6px);opacity:.15;letter-spacing:.3em}to{filter:blur(0);opacity:1;letter-spacing:normal}}
@supports (animation-timeline: view()){
  .lux-reveal,[data-testid="stMain"] [data-testid="stFileUploader"]{
    animation:lux-rise linear both;animation-timeline:view();animation-range:entry 0% entry 85%}
  .lux-g5>.lux-card,.lux-g6>.lux-card,.lux-stats>.lux-card,.lux-bento>.lux-card{
    animation:lux-rise linear both;animation-timeline:view();animation-range:entry 0% entry 75%}
  .lux-hero-art{animation:lux-parallax linear both;animation-timeline:scroll(nearest);animation-range:0 560px}
  .lux-hero-copy{animation:lux-drift linear both;animation-timeline:scroll(nearest);animation-range:0 560px}
  .lux-flow::before{animation:lux-beamfill linear both;animation-timeline:view();animation-range:cover 15% cover 45%}
  .lux-stat .lux-count{animation:lux-count linear both;animation-timeline:view();animation-range:entry 0% cover 35%}
  .lux-section .lux-h2{animation:lux-wipe linear both;animation-timeline:view();animation-range:entry 10% entry 100%}
  .lux-viewer .lux-tag{animation:lux-tagin linear both;animation-timeline:view();animation-range:entry 0% entry 100%}
}
@supports not (animation-timeline: view()){
  .lux-reveal{animation:lux-in .9s var(--lux-ease) both}
  .lux-g5>.lux-card,.lux-g6>.lux-card,.lux-stats>.lux-card,.lux-bento>.lux-card{animation:lux-in .8s var(--lux-ease) both;
    animation-delay:calc(var(--i,0)*.08s)}
  .lux-flow::before{animation:lux-beamfill 2s .4s var(--lux-ease) both}
}


/* ---------- security & compliance components */
.lux-risk{display:grid;gap:.55rem;padding:1.1rem 1.25rem}
.lux-risk .row{display:grid;grid-template-columns:92px 190px 1fr;gap:.8rem;align-items:start;font-size:.86rem}
.lux-sev{display:inline-flex;justify-content:center;padding:.15rem .5rem;border-radius:999px;font:800 .66rem var(--lux-mono);
  letter-spacing:.08em;text-transform:uppercase;color:var(--c);background:color-mix(in srgb,var(--c) 12%,var(--lux-surface));
  border:1px solid color-mix(in srgb,var(--c) 40%,transparent)}
.lux-risk .k{font-weight:700;color:var(--lux-text)} .lux-risk .d{color:var(--lux-muted);overflow-wrap:anywhere}
.lux-risk .d code{font-family:var(--lux-mono);font-size:.78rem;color:var(--lux-dim)}
.lux-reg{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:.8rem}
.lux-reg .lux-card{padding:1rem 1.1rem}
.lux-reg .id{font:800 .72rem var(--lux-mono);letter-spacing:.08em;color:var(--lux-orange)}
.lux-reg b{display:block;color:var(--lux-text);font-size:.95rem;margin:.2rem 0 .15rem}
.lux-reg .j{color:var(--lux-muted);font-size:.8rem}
.lux-reg .t{margin-top:.5rem;display:flex;flex-wrap:wrap;gap:.3rem}
.lux-reg .t span{font:700 .68rem var(--lux-mono);padding:.12rem .4rem;border-radius:6px;color:var(--lux-text);
  background:var(--lux-surface);border:1px solid var(--lux-line)}
.lux-disclaimer{margin-top:.7rem;color:var(--lux-dim);font-size:.78rem}
.lux-restored{padding:1.1rem 1.25rem;white-space:pre-wrap;font-size:.92rem;line-height:1.65;color:var(--lux-text);overflow-wrap:anywhere}
.lux-restored mark{background:color-mix(in srgb,var(--lux-orange) 18%,transparent);color:var(--lux-text);
  border-bottom:2px solid var(--lux-orange);border-radius:3px;padding:0 .15em}
.lux-posture{display:grid;gap:.1rem;padding:.6rem 1.2rem}
.lux-posture .row{display:grid;grid-template-columns:26px 1fr auto;gap:.7rem;align-items:center;padding:.55rem 0;
  border-bottom:1px solid var(--lux-line)}
.lux-posture .row:last-child{border-bottom:none}
.lux-posture .st{width:22px;height:22px;border-radius:50%;display:grid;place-items:center;color:#fff;background:var(--c)}
.lux-posture b{color:var(--lux-text);font-size:.9rem;display:block}
.lux-posture span.d{color:var(--lux-muted);font-size:.8rem;display:block;overflow-wrap:anywhere}
.lux-posture .v{font:600 .76rem var(--lux-mono);color:var(--lux-muted);text-align:right;max-width:260px;overflow-wrap:anywhere}
.lux-events{font:.76rem/1.6 var(--lux-mono);color:var(--lux-muted);padding:.9rem 1.1rem;overflow-x:auto;white-space:pre}
.lux-login{max-width:440px;margin:8vh auto 1.2rem;padding:1.6rem 1.7rem;text-align:left}
.lux-login b{display:block;font-size:1.25rem;color:var(--lux-text);margin:.6rem 0 .3rem}
.lux-login p{color:var(--lux-muted);font-size:.9rem;margin:0}
@media (max-width:900px){.lux-risk .row{grid-template-columns:80px 1fr}.lux-risk .row .d{grid-column:1/-1}}
/* ---------- responsive + accessibility */
@media (max-width:1100px){.lux-g6{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media (max-width:900px){.lux-hero{grid-template-columns:1fr}.lux-hero-art{height:340px}
  .lux-g5{grid-template-columns:repeat(2,minmax(0,1fr))}.lux-stats{grid-template-columns:repeat(2,minmax(0,1fr))}
  .lux-bento{grid-template-columns:1fr}.lux-orbit,.lux-float,.lux-flow::before,.lux-flow::after{display:none}
  .lux-pipe{grid-template-columns:repeat(5,minmax(64px,1fr));overflow-x:auto}.lux-cmp{grid-template-columns:1fr}
  .lux-doc{flex-wrap:wrap}.lux-status{margin-left:0;align-items:flex-start;text-align:left}.lux-bar{grid-template-columns:110px 1fr 40px}}
@media (max-width:560px){.lux-g5,.lux-g6,.lux-stats{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (pointer:coarse){#lux-glow{display:none}}
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{animation:none!important;transition:none!important}
  .lux-tg{opacity:1;scale:1}.lux-hide{opacity:0}#lux-splash{display:none}
  .lux-count{--lux-num:var(--to)!important}      /* counters show their final value without animating */
}
"""

_JS = r"""
<script>
(() => {
  // st.html strips style tags, so the stylesheet is installed from here (refreshed on every rerun).
  // Keep this script free of "<" followed by a letter or "/": the sanitizer drops scripts that contain it.
  let css = document.getElementById('lux-css');
  if (!css) { css = document.createElement('style'); css.id = 'lux-css'; document.head.appendChild(css); }
  css.textContent = __LUX_CSS__;
  if (window.__luxInit) return;
  window.__luxInit = true;

  const root = document.documentElement;
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const main = () => document.querySelector('[data-testid="stMain"]');
  const lerp = (a, b, t) => a + (b - a) * t;

  /* ---------- follow Streamlit's light/dark setting (menu > Settings > Theme) */
  let net = { line: '47,111,235', alpha: 0.16, dot: 'rgba(11,31,58,.32)' };
  const readNet = () => {
    const cs = getComputedStyle(root);
    net = { line: cs.getPropertyValue('--lux-net-line').trim(), alpha: parseFloat(cs.getPropertyValue('--lux-net-alpha')) || 0.16,
            dot: cs.getPropertyValue('--lux-net-dot').trim() };
  };
  const detectTheme = () => {
    const app = document.querySelector('[data-testid="stApp"]');
    if (!app) return;
    const rgb = (getComputedStyle(app).color.match(/\d+/g) || []).map(Number);
    if (rgb.length < 3) return;
    const mode = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) > 140 ? 'dark' : 'light';  // light text => dark theme
    if (root.dataset.luxTheme !== mode) { root.dataset.luxTheme = mode; readNet(); }
  };
  detectTheme(); readNet();
  setInterval(detectTheme, 400);

  /* ---------- intro splash, once per browser session */
  try {
    if (!reduce && !sessionStorage.getItem('luxSplash')) {
      sessionStorage.setItem('luxSplash', '1');
      const sp = document.createElement('div');
      sp.id = 'lux-splash';
      // built with DOM calls: markup strings inside the script would make the sanitizer drop it
      const core = document.createElement('div'); core.className = 'core';
      const ic = document.createElement('i'); ic.className = 'lux-ico lux-i-shield'; ic.style.setProperty('--s', '44px');
      const label = document.createElement('p'); label.textContent = 'Initializing secure gateway';
      core.appendChild(ic); sp.append(core, label);
      document.body.appendChild(sp);
      setTimeout(() => sp.remove(), 2600);
    }
  } catch (e) { /* storage blocked: skip the splash */ }

  /* ---------- scroll progress bar + glass header */
  const bar = document.createElement('div');
  bar.className = 'lux-progress';
  document.body.appendChild(bar);
  let ticking = false;
  document.addEventListener('scroll', () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      const m = main();
      if (m) {
        const max = m.scrollHeight - m.clientHeight;
        bar.style.transform = `scaleX(${max > 0 ? m.scrollTop / max : 0})`;
        document.querySelector('[data-testid="stHeader"]')?.classList.toggle('lux-scrolled', m.scrollTop > 8);
      }
      ticking = false;
    });
  }, { capture: true, passive: true });

  /* ---------- interactive particle network */
  const cv = document.createElement('canvas');
  cv.id = 'lux-net';
  document.body.prepend(cv);
  const ctx = cv.getContext('2d');
  let W = 0, H = 0, pts = [], raf = 0;
  const mouse = { x: -9999, y: -9999 };
  const size = () => {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    W = innerWidth; H = innerHeight;
    cv.width = W * dpr; cv.height = H * dpr;
    cv.style.width = W + 'px'; cv.style.height = H + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const n = Math.round(Math.min(120, (W * H) / 14000));
    pts = Array.from({ length: n }, () => ({
      x: Math.random() * W, y: Math.random() * H, vx: (Math.random() - 0.5) * 0.3, vy: (Math.random() - 0.5) * 0.3,
      r: Math.random() * 1.6 + 0.6, hot: Math.random() < 0.16,
    }));
  };
  const draw = () => {
    ctx.clearRect(0, 0, W, H);
    for (const p of pts) {
      if (reduce) break;
      p.x += p.vx; p.y += p.vy;
      if (p.x < 0 || p.x > W) p.vx *= -1;
      if (p.y < 0 || p.y > H) p.vy *= -1;
      const dx = p.x - mouse.x, dy = p.y - mouse.y, d = Math.hypot(dx, dy);
      if (d < 160 && d > 0) { p.x += (dx / d) * 0.9; p.y += (dy / d) * 0.9; }
    }
    ctx.lineWidth = 1;
    for (let i = 0; i < pts.length; i++) {
      const a = pts[i];
      for (let j = i + 1; j < pts.length; j++) {
        const b = pts[j], dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy;
        if (d2 < 17000) {
          ctx.strokeStyle = `rgba(${net.line},${(1 - Math.sqrt(d2) / 130) * net.alpha})`;
          ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
        }
      }
      const md = Math.hypot(mouse.x - a.x, mouse.y - a.y);
      if (md < 220) {
        ctx.strokeStyle = `rgba(243,111,33,${(1 - md / 220) * 0.55})`;
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(mouse.x, mouse.y); ctx.stroke();
      }
      ctx.fillStyle = a.hot ? 'rgba(243,111,33,.9)' : net.dot;
      ctx.beginPath(); ctx.arc(a.x, a.y, a.hot ? a.r + 0.6 : a.r, 0, 6.2832); ctx.fill();
    }
    if (!reduce && !document.hidden) raf = requestAnimationFrame(draw);
  };
  size(); draw();
  addEventListener('resize', () => { size(); if (reduce) draw(); });
  document.addEventListener('visibilitychange', () => { cancelAnimationFrame(raf); if (!document.hidden) draw(); });

  /* ---------- smoothed cursor glow */
  const glow = document.createElement('div');
  glow.id = 'lux-glow';
  document.body.appendChild(glow);
  let gx = innerWidth / 2, gy = innerHeight / 2, tx = gx, ty = gy;
  const glowLoop = () => {
    gx = lerp(gx, tx, 0.12); gy = lerp(gy, ty, 0.12);
    glow.style.transform = `translate3d(${gx}px,${gy}px,0)`;
    requestAnimationFrame(glowLoop);
  };
  if (!reduce) glowLoop();
  document.addEventListener('pointerleave', () => { document.body.classList.remove('lux-pointer'); mouse.x = mouse.y = -9999; });

  /* ---------- pointer: spotlight, 3D tilt + glare, hero tilt, magnetic buttons */
  let tiltCard = null, magnet = null;
  document.addEventListener('pointermove', (e) => {
    mouse.x = e.clientX; mouse.y = e.clientY; tx = e.clientX; ty = e.clientY;
    document.body.classList.add('lux-pointer');
    const t = e.target && e.target.closest ? e.target : null;
    if (!t) return;
    const spot = t.closest('.lux-spot');
    if (spot) {
      const r = spot.getBoundingClientRect();
      spot.style.setProperty('--mx', `${e.clientX - r.left}px`);
      spot.style.setProperty('--my', `${e.clientY - r.top}px`);
    }
    if (reduce) return;
    const card = t.closest('.lux-tiltcard');
    if (tiltCard && tiltCard !== card) { tiltCard.style.setProperty('--rx', '0deg'); tiltCard.style.setProperty('--ry', '0deg'); }
    tiltCard = card;
    if (card) {
      const r = card.getBoundingClientRect();
      const px = (e.clientX - r.left) / r.width, py = (e.clientY - r.top) / r.height;
      card.style.setProperty('--ry', `${((px - 0.5) * 14).toFixed(2)}deg`);
      card.style.setProperty('--rx', `${((0.5 - py) * 12).toFixed(2)}deg`);
      card.style.setProperty('--gx', `${(px * 100).toFixed(1)}%`);
      card.style.setProperty('--gy', `${(py * 100).toFixed(1)}%`);
    }
    const art = document.querySelector('.lux-tilt');
    if (art) {
      const r = art.getBoundingClientRect();
      const x = (e.clientX - (r.left + r.width / 2)) / r.width, y = (e.clientY - (r.top + r.height / 2)) / r.height;
      const near = Math.abs(x) < 1.6 && Math.abs(y) < 1.6;
      art.style.setProperty('--ry', near ? `${(x * 16).toFixed(2)}deg` : '0deg');
      art.style.setProperty('--rx', near ? `${(-y * 12).toFixed(2)}deg` : '0deg');
    }
    const btn = t.closest('[data-testid="stMain"] [data-testid^="stBaseButton"]');
    if (magnet && magnet !== btn) magnet.style.translate = '0 0';
    magnet = btn;
    if (btn && !btn.disabled) {
      const r = btn.getBoundingClientRect();
      btn.style.translate = `${((e.clientX - r.left - r.width / 2) * 0.22).toFixed(1)}px ${((e.clientY - r.top - r.height / 2) * 0.35).toFixed(1)}px`;
    }
  }, { passive: true });

  /* ---------- "decrypt" text effect for [data-scramble] */
  const GL = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#%&*@$/';
  const scramble = (el) => {
    const final = el.getAttribute('data-scramble');
    if (!final || el.dataset.done) return;
    el.dataset.done = '1';
    if (reduce) { el.textContent = final; return; }
    const start = performance.now(), dur = 700 + final.length * 24;
    const tick = (now) => {
      const p = Math.min(1, (now - start) / dur);
      let out = '';
      for (let i = 0; i < final.length; i++) {
        const c = final[i];
        out += (c === ' ' || i / final.length < p * 1.2 - 0.15) ? c : GL[(Math.random() * GL.length) | 0];
      }
      el.textContent = out;
      if (p < 1) requestAnimationFrame(tick); else el.textContent = final;
    };
    requestAnimationFrame(tick);
  };
  const io = new IntersectionObserver((entries) => entries.forEach((en) => {
    if (en.isIntersecting) { scramble(en.target); io.unobserve(en.target); }
  }), { threshold: 0.3 });
  let scanQueued = false;
  const scan = () => {
    scanQueued = false;
    document.querySelectorAll('[data-scramble]:not([data-obs])').forEach((el) => { el.dataset.obs = '1'; io.observe(el); });
  };
  new MutationObserver(() => { if (!scanQueued) { scanQueued = true; requestAnimationFrame(scan); } })
    .observe(document.body, { childList: true, subtree: true });
  scan();

  /* ---------- inertial smooth scrolling for the main column */
  let target = null, animating = false;
  const scrollableInside = (el, m, dy) => {
    for (; el && el !== m; el = el.parentElement) {
      const oy = getComputedStyle(el).overflowY;
      if ((oy === 'auto' || oy === 'scroll') && el.scrollHeight > el.clientHeight + 1) {
        if (dy > 0 && el.scrollTop + el.clientHeight < el.scrollHeight - 1) return true;
        if (dy < 0 && el.scrollTop > 0) return true;
      }
    }
    return false;
  };
  let last = 0;
  const step = (now) => {
    const m = main();
    if (!m || target === null) { animating = false; return; }
    // time-based easing: same feel at 60/120 Hz or when frames are dropped
    const dt = Math.min(64, now - (last || now - 16.7)); last = now;
    const k = 1 - Math.pow(0.88, dt / 16.7);
    const delta = target - m.scrollTop;
    const move = Math.sign(delta) * Math.max(1, Math.abs(delta) * k);
    if (Math.abs(delta) <= 1) { m.scrollTop = target; animating = false; last = 0; return; }
    m.scrollTop += move;
    requestAnimationFrame(step);
  };
  document.addEventListener('wheel', (e) => {
    const m = main();
    if (reduce || !m || e.ctrlKey || e.shiftKey || !m.contains(e.target)) return;
    if (e.target.closest('[data-testid="stDataFrame"],[data-baseweb="popover"],textarea,canvas,[data-testid="stJson"]')) return;
    if (scrollableInside(e.target, m, e.deltaY)) return;
    e.preventDefault();
    const dy = e.deltaMode === 1 ? e.deltaY * 32 : e.deltaY;
    if (!animating) target = m.scrollTop;
    target = Math.max(0, Math.min(m.scrollHeight - m.clientHeight, target + dy));
    if (!animating) { animating = true; requestAnimationFrame(step); }
  }, { passive: false, capture: true });
  document.addEventListener('keydown', () => { animating = false; target = null; });

  /* ---------- hovering a placeholder highlights every occurrence of it */
  document.addEventListener('mouseover', (e) => {
    const t = e.target.closest && e.target.closest('.lux-tag');
    document.querySelectorAll('.lux-tag.lux-hl').forEach((x) => x.classList.remove('lux-hl'));
    if (!t) return;
    t.closest('.lux-viewer')?.querySelectorAll('.lux-tag').forEach((x) => {
      if (x.textContent === t.textContent) x.classList.add('lux-hl');
    });
  });
})();
</script>
"""


def inject() -> None:
    # "<" is escaped so the sanitizer never mistakes CSS like '<angle>' for a tag inside the script
    css = json.dumps(_TOKENS + _CSS + _icon_css()).replace("<", "\\u003c")
    st.html(_JS.replace("__LUX_CSS__", css), unsafe_allow_javascript=True)


# ------------------------------------------------------------------ sidebar components (compact)
def sidebar_brand() -> str:
    return (f'<div class="sb-brand"><div class="sb-mark">{icon("shield", 17)}</div>'
            f'<div><b>PII Gateway</b><small>Secure document processing</small></div></div>')


def sidebar_engines(rows: Iterable[tuple]) -> str:
    return "".join(f'<div class="sb-engine"><span>{_e(k)}</span><b class="{"bad" if bad else ""}">{_e(v)}</b></div>'
                   for k, v, bad in rows)


def sidebar_label(text: str) -> str:
    return f'<div class="sb-label">{_e(text)}</div>'


# ------------------------------------------------------------------ main-area components
def _glare() -> str:
    return '<span class="lux-glare"></span>'


def hero(compact: bool = False) -> str:
    lines = [(52, 150), (86, 84), (120, 190), (154, 70), (188, 170), (222, 96), (256, 150)]
    art_lines = "".join(f'<div class="lux-ln" style="top:{t}px;width:{w}px"></div>' for t, w in lines)
    tags = [(86, "[PERSON_1]", 0.6), (154, "[EMAIL_1]", 1.6), (222, "[PHONE_1]", 2.6)]
    art_tags = "".join(
        f'<div class="lux-hide" style="top:{t - 1}px;left:112px;width:96px;animation-delay:{d}s"></div>'
        f'<div class="lux-tg" style="top:{t - 5}px;left:112px;animation-delay:{d}s">{label}</div>'
        for t, label, d in tags)
    floats = [("[SSN_1]", "var(--lux-red)", "8%", "62%", "0s"), ("[IBAN_1]", "var(--lux-violet)", "2%", "18%", "1.2s"),
              ("[EMPLOYEE_ID_1]", "var(--lux-blue)", "72%", "84%", "2.1s")]
    float_html = "".join(f'<span class="lux-float" style="--c:{c};left:{x};top:{y};--d:{d}">{t}</span>'
                         for t, c, x, y, d in floats)
    chips = [("chip", "Runs 100% locally"), ("lock", "Fails closed"), ("pin", "Source-traceable"),
             ("eyeoff", "No raw PII in reports")]
    chip_html = "".join(f'<span class="lux-chip">{icon(i, 15)}{_e(t)}</span>' for i, t in chips)
    cta = "" if compact else ('<div class="lux-cta"><span class="lux-mouse"></span>'
                              'Drop a document below, or scroll to see how it works</div>')
    title = "PII Sanitization Gateway"
    return f"""
<section class="lux-hero">
  <div class="lux-hero-copy">
    <span class="lux-eyebrow"><i></i>Privacy-first document AI</span>
    <h1 class="lux-h1" data-scramble="{title}">{title}</h1>
    <p class="lux-lead">Upload PDF, DOCX or PPTX files. Personal data is detected, replaced with consistent
      placeholders such as <code>[PERSON_3]</code> and <code>[EMAIL_2]</code>, then re-scanned by an independent
      check. Only <b>SAFE</b> documents are released to downloads or AI analysis.</p>
    <div class="lux-chips">{chip_html}</div>{cta}
  </div>
  <div class="lux-hero-art" aria-hidden="true">
    <div class="lux-tilt">
      <div class="lux-orbit o1"><span class="sat"></span></div><div class="lux-orbit o2"><span class="sat"></span></div>
      <div class="lux-sheet s3"></div><div class="lux-sheet s2"></div>
      <div class="lux-sheet s1">{art_lines}{art_tags}<div class="lux-beam"></div></div>
      {float_html}
      <div class="lux-badge">{icon("shield", 34)}</div>
    </div>
  </div>
</section>{ticker()}"""


def ticker() -> str:
    """Two infinite rows of PII types (fictional example values) sliding in opposite directions."""
    row1 = [("PERSON", "Rahul Sharma"), ("EMAIL", "rahul@example.com"), ("PHONE", "+91 98765 43210"),
            ("SSN", "219-09-9999"), ("PAN", "ABCPE1234F"), ("PASSPORT", "K1234567"), ("IBAN", "GB82 WEST …"),
            ("CREDIT_CARD", "4111 1111 …")]
    row2 = [("EMPLOYEE_ID", "EMP-1042"), ("ADDRESS", "42 Maple Street"), ("DOB", "14/03/1994"),
            ("IP_ADDRESS", "192.168.10.45"), ("AADHAAR", "2341 …"), ("NATIONAL_ID", "QQ 12 34 56 C"),
            ("BANK_ACCOUNT", "Acct 0012 …"), ("PERSON", "N. Osadebe")]

    def chips(items):
        one = "".join(f'<span class="lux-tick" style="--c:{_tag_color(k)}"><s>{_e(v)}</s>[{k}]</span>' for k, v in items)
        return one + one  # duplicated so the -50% marquee loops seamlessly

    return (f'<div class="lux-ticker" aria-hidden="true"><div class="lux-row">{chips(row1)}</div>'
            f'<div class="lux-row rev">{chips(row2)}</div></div>')


def landing() -> str:
    steps = [("file", "Extract", "Text, tables, notes and file properties, with OCR for scans and screenshots."),
             ("scan", "Detect", "35 regex and checksum recognizers plus NER and document context for names."),
             ("redact", "Redact", "Typed, consistent placeholders keep the meaning but remove identities."),
             ("shield", "Verify", "A second, independent scan. Anything left over is remediated or blocked."),
             ("send", "Release", "Only SAFE text reaches downloads or AI, after an egress re-check.")]
    cards = "".join(
        f'<div class="lux-card lux-spot lux-tiltcard lux-step" style="--i:{i}">{_glare()}<span class="n">0{i + 1}</span>'
        f'<div class="ic">{icon(ic, 22)}</div><b>{t}</b><p>{d}</p></div>'
        for i, (ic, t, d) in enumerate(steps))
    stats = [(35, "var(--lux-orange)", "Recognizers", "Regex plus Luhn, Verhoeff, mod-97 and SSN rules"),
             (3, "var(--lux-blue)", "Formats", "PDF, DOCX and PPTX, including scanned pages"),
             (2, "var(--lux-green)", "Independent scans", "Detector and safety net before anything is released"),
             (247, "var(--lux-violet)", "Automated tests", "All passing, all on fake data")]
    stat_html = "".join(
        f'<div class="lux-card lux-spot lux-tiltcard lux-stat" style="--c:{c};--i:{i}">{_glare()}'
        f'<div class="num"><span class="lux-count" style="--to:{n}" aria-hidden="true"></span><span class="lux-sr">{n}</span></div>'
        f'<div class="cap"><b>{t}</b>{d}</div></div>'
        for i, (n, c, t, d) in enumerate(stats))
    variants = ["Naomi K. Osadebe", "N. Osadebe", "Osadebe", "NAOMI OSADEBE"]
    mapping = "".join(f'<div style="--i:{i}"><s>{v}</s><em></em><b>[PERSON_1]</b></div>' for i, v in enumerate(variants))
    packets = "".join(f'<span class="lux-pkt" style="--d:{d}s"></span>' for d in (0, 1, 2))
    paths = ["page 21", "slide 3 | Table 2 | row 1 | col 2", "table 0 | row 2 | col 1", "metadata | field author"]
    path_html = "".join(f'<span>{icon("pin", 13)}{_e(p)}</span>' for p in paths)
    bento = f"""
<div class="lux-bento">
  <div class="lux-card lux-spot lux-tiltcard" style="--i:0">{_glare()}<h4>One person, one tag</h4>
    <p class="d">Every spelling of a confirmed person shares a placeholder, so the AI still knows who did what.</p>
    <div class="lux-map">{mapping}</div></div>
  <div class="lux-card lux-spot lux-tiltcard" style="--i:1">{_glare()}<h4>Fails closed</h4>
    <p class="d">Verified documents pass the gate. Anything unreadable or uncertain stops there.</p>
    <div class="lux-lanes"><span class="lux-lbl a">SAFE → RELEASED</span><div class="lux-lane a">{packets}</div>
      <div class="lux-gate"></div><div class="lux-lane b">{packets}</div><span class="lux-lbl b">BLOCKED → WITHHELD</span></div></div>
  <div class="lux-card lux-spot lux-tiltcard" style="--i:2">{_glare()}<h4>Traceable to the cell</h4>
    <p class="d">Each finding points to its page, slide, shape, table cell or file property.</p>
    <div class="lux-path">{path_html}</div></div>
</div>"""
    return f"""
<div class="lux-section lux-reveal"><div class="lux-kicker">How it works</div>
  <div class="lux-h2">Five stages, one gate</div>
  <p class="lux-sub">Nothing reaches the AI before the privacy check passes.</p></div>
<div class="lux-flow"><div class="lux-grid lux-g5">{cards}</div></div>
<div class="lux-section lux-reveal"><div class="lux-kicker">Built in</div><div class="lux-h2">Engineered for reliability</div></div>
<div class="lux-stats">{stat_html}</div>
<div class="lux-section lux-reveal"><div class="lux-kicker">Design principles</div><div class="lux-h2">Privacy you can explain</div></div>
{bento}
<p class="lux-note lux-reveal">Nothing uploaded yet. Try the fictional files in <code>sample_test_cases/inputs/</code>
or the three Cadence sample files.</p>"""


def view_title(kicker: str, title: str, sub: str) -> str:
    return (f'<div class="lux-section top"><div class="lux-kicker">{_e(kicker)}</div>'
            f'<div class="lux-h2">{_e(title)}</div><p class="lux-sub">{_e(sub)}</p></div>')


def label(text: str) -> str:
    return f'<div class="lux-label">{_e(text)}</div>'


_FTYPE = {".pdf": ("#FF5E62", "#B4232A"), ".docx": ("#5B9DFF", "#2A5DC4"), ".pptx": ("#F36F21", "#B9440A")}
_FAIL_STAGE = {"extraction_failed": 0, "incomplete_extraction": 0, "no_content": 0,
               "residual_pii": 3, "verification_error": 3}
FIXES = {
    "extraction_failed": "Check that the file is a valid, unprotected PDF, DOCX or PPTX. Re-export it from the source "
                         "application and upload it again.",
    "incomplete_extraction": "Scanned pages or images could not be read. Make sure OCR (Tesseract) is available, or "
                             "provide a text-based version of the document.",
    "no_content": "Confirm the document is not empty or image-only. If it is scanned, make sure OCR is available.",
    "residual_pii": "Review the residual findings in Findings and the source document. Manual redaction may be required.",
    "verification_error": "Process the document again. If it fails repeatedly, review the audit report.",
}


def _verdict(safe: bool, small: bool = False) -> str:
    color = "var(--lux-green)" if safe else "var(--lux-red)"
    return (f'<span class="lux-verdict{" sm" if small else ""}" style="--c:{color}">'
            f'{icon("check" if safe else "x", 13 if small else 16)}{"SAFE" if safe else "BLOCKED"}</span>')


def _ftype(ext: str, small: bool = False) -> str:
    c1, c2 = _FTYPE.get(ext, ("#8FA0BA", "#4A5A75"))
    return f'<div class="lux-ftype{" sm" if small else ""}" style="--c1:{c1};--c2:{c2}">{_e(ext[1:].upper() or "FILE")}</div>'


def doc_header(name: str, ext: str, safe: bool, reason: str, summary: Dict, message: str) -> str:
    pills = [f"{summary['blocks']} text blocks", "OCR used" if summary.get("ocr_used") else "native text"]
    if summary.get("people"):
        pills.append(f"{summary['people']} people")
    pill_html = "".join(f'<span class="lux-pill">{_e(p)}</span>' for p in pills)
    color = "var(--lux-green)" if safe else "var(--lux-red)"
    fix = "" if safe or reason not in FIXES else f'<div class="lux-fix"><b>Suggested action:</b> {_e(FIXES[reason])}</div>'
    return f"""
<div class="lux-card lux-spot lux-reveal {'' if safe else 'blocked'}" style="padding:0">
  <div class="lux-doc" style="margin:0">
    <span class="lux-ring" style="--rc:{color}"></span>
    {_ftype(ext)}
    <div><h3>{_e(name)}</h3><div class="meta">{pill_html}</div></div>
    <div class="lux-status">{_verdict(safe)}<small>{_e(reason.replace("_", " "))} · {_e(message)}</small></div>
  </div>{f'<div style="padding:0 1.45rem 1.2rem">{fix}</div>' if fix else ''}
</div>"""


def stepper(safe: bool, reason: str, summary: Dict, passes: int) -> str:
    t = summary.get("timings", {})
    metas = [f"{summary['blocks']} blocks · {t.get('extract', 0)}s",
             f"{summary['findings']} findings · {t.get('detect', 0)}s",
             f"{summary['redacted']} replaced",
             f"{passes} scan pass{'es' if passes != 1 else ''} · {t.get('redact_verify', 0)}s",
             "released" if safe else "withheld"]
    names = [("file", "Extract"), ("scan", "Detect"), ("redact", "Redact"), ("shield", "Verify"), ("send", "Release")]
    fail_at = None if safe else _FAIL_STAGE.get(reason, 3)
    nodes = []
    for i, (ic, lab) in enumerate(names):
        if fail_at is None or i < fail_at:
            state, color, glyph, meta = "", "var(--lux-green)", icon(ic, 19), metas[i]
        elif i == fail_at:
            state, color, glyph, meta = "fail", "var(--lux-red)", icon("x", 19), reason.replace("_", " ")
        else:
            state, color, glyph, meta = "", "var(--lux-dim)", icon("lock", 17), "locked"
        nodes.append(f'<div class="lux-node {state}" style="--i:{i};--c:{color}"><div class="o">{glyph}</div>'
                     f'<b>{lab}</b><span>{_e(meta)}</span></div>')
    width = "100%" if fail_at is None else f"{fail_at * 25}%"
    return (f'<div class="lux-card lux-pipe lux-reveal"><div class="lux-track {"ok" if safe else "fail"}">'
            f'<i style="--w:{width}"></i></div>{"".join(nodes)}</div>')


def metrics(summary: Dict) -> str:
    items = [("Text blocks", summary["blocks"], None), ("PII found", summary["findings"], "var(--lux-amber)"),
             ("Redacted", summary["redacted"], "var(--lux-orange)"), ("People", summary["people"], None),
             ("Needs review", summary["needs_review"], "var(--lux-yellow)" if summary["needs_review"] else None),
             ("Seconds", summary["seconds"], None)]
    cards = []
    for i, (lab, value, color) in enumerate(items):
        style = f"--i:{i};" + (f"--c:{color};" if color else "")
        if isinstance(value, int):
            val = (f'<div class="val lux-count" style="--to:{value}" aria-hidden="true"></div>'
                   f'<span class="lux-sr">{value}</span>')
        else:
            val = f'<div class="val">{_e(value)}</div>'
        cards.append(f'<div class="lux-card lux-spot lux-tiltcard lux-metric" style="{style}">{_glare()}'
                     f'<div class="lbl">{lab}</div>{val}</div>')
    return f'<div class="lux-grid lux-g6" style="margin-top:1rem">{"".join(cards)}</div>'


def warning(text: str) -> str:
    return f'<div class="lux-warn">{icon("alert", 16)}<span>{_e(text)}</span></div>'


def doc_row(name: str, ext: str, safe: bool, findings: int, active: bool) -> str:
    return (f'<div class="lux-drow {"active" if active else ""}">{_ftype(ext, True)}<span class="name">{_e(name)}</span>'
            f'{_verdict(safe, True)}<span class="meta">{findings} findings</span></div>')


def doc_context(name: str, ext: str, safe: bool, reason: str) -> str:
    return (f'<div class="lux-card lux-ctx">{_ftype(ext, True)}<span class="name">{_e(name)}</span>{_verdict(safe, True)}'
            f'<span class="meta">{_e(reason.replace("_", " "))}</span></div>')


def empty(title: str, text: str, kind: str = "") -> str:
    return (f'<div class="lux-card lux-empty lux-reveal {kind}"><div class="mk">{icon("lock" if kind == "bad" else "inbox", 22)}</div>'
            f'<div><b>{_e(title)}</b><p>{_e(text)}</p></div></div>')


def output_row(title: str, desc: str, available: bool) -> str:
    return f'<div class="lux-out"><b>{_e(title)}</b><span class="{"" if available else "na"}">{_e(desc)}</span></div>'


TAG_COLORS = {"PERSON": "var(--lux-orange)", "EMAIL": "var(--lux-blue)", "PHONE": "var(--lux-violet)",
              "EMPLOYEE_ID": "var(--lux-yellow)", "ADDRESS": "var(--lux-teal)", "SSN": "var(--lux-red)",
              "CREDIT_CARD": "var(--lux-red)", "IBAN": "var(--lux-red)", "PAN": "var(--lux-red)",
              "PASSPORT": "var(--lux-red)", "AADHAAR": "var(--lux-red)", "NATIONAL_ID": "var(--lux-red)",
              "BANK_ACCOUNT": "var(--lux-violet)", "DOB": "var(--lux-teal)", "IP_ADDRESS": "var(--lux-blue)"}
_TAG_RE = re.compile(r"\[([A-Z][A-Z_]*?)_(\d+)\]")


def _tag_color(kind: str) -> str:
    return TAG_COLORS.get(kind, "var(--lux-green)")


def _tags(escaped: str) -> str:
    return _TAG_RE.sub(lambda m: f'<span class="lux-tag" style="--c:{_tag_color(m.group(1))}">'
                                 f'[{m.group(1)}_{m.group(2)}]</span>', escaped)


def sanitized_view(blocks: Iterable, placeholders: int) -> str:
    rows, n = [], 0
    for block in blocks:
        n += 1
        rows.append(f'<div class="lux-blk"><div class="lux-src">{icon("pin", 12)}{_e(block.source)}</div>'
                    f'<div class="lux-txt">{_tags(_e(block.text))}</div></div>')
    head = (f'<div class="lux-vhead"><span class="lux-pill">{n} blocks</span>'
            f'<span class="lux-pill">{placeholders} placeholders</span>'
            f'<span>Hover a tag to highlight every occurrence.</span></div>')
    return f'<div class="lux-viewer">{head}{"".join(rows)}</div>'


def compare(original: Optional[str], sanitized: str) -> str:
    left = (f'<div class="lux-txt">{_e(original)}</div>' if original is not None else
            '<div class="hid">Hidden. The original contains raw personal data. To display it on this machine, enable '
            '“Show original text in Compare” under System &amp; settings in the sidebar.</div>')
    return (f'<div class="lux-cmp lux-reveal"><div class="lux-card"><div class="ch">Original</div>{left}</div>'
            f'<div class="lux-card"><div class="ch">Sanitized</div><div class="lux-txt">{_tags(_e(sanitized))}</div></div></div>')


def type_bars(counts: Dict[str, int]) -> Optional[str]:
    if not counts:
        return None
    top = max(counts.values())
    rows = "".join(
        f'<div class="lux-bar" style="--c:{_tag_color(k)};--i:{i}"><span class="t">{_e(k)}</span>'
        f'<span class="r"><i style="--w:{v / top * 100:.1f}%"></i></span><span class="c">{v}</span></div>'
        for i, (k, v) in enumerate(sorted(counts.items(), key=lambda kv: -kv[1])))
    return f'<div class="lux-card lux-bars">{rows}</div>'


def footer() -> str:
    return '<div class="lux-foot"><span>Optiv Case Study 2 · Text Analysis &amp; PII Detection</span></div>'


# ------------------------------------------------------------------ security & compliance components
_SEV = {"high": "var(--lux-red)", "review": "var(--lux-yellow)", "info": "var(--lux-blue)"}


def risk_panel(findings: List) -> str:
    rows = "".join(
        f'<div class="row"><span class="lux-sev" style="--c:{_SEV.get(f.severity, "var(--lux-dim)")}">{_e(f.severity)}</span>'
        f'<span class="k">{_e(f.kind.replace("_", " "))}</span>'
        f'<span class="d">{_e(f.detail)} <code>{_e(f.location)}</code></span></div>' for f in findings)
    return f'<div class="lux-card lux-risk lux-reveal">{rows}</div>'


def compliance_panel(rows: List[Dict], disclaimer: str) -> str:
    cards = "".join(
        f'<div class="lux-card lux-spot"><div class="id">{_e(r["id"])}</div><b>{_e(r["name"])}</b>'
        f'<div class="j">{_e(r["jurisdiction"])} · {_e(r["reference"])}</div>'
        f'<div class="t">{"".join(f"<span>{_e(t)}</span>" for t in r["types"])}'
        f'<span>{r["occurrences"]} occurrence{"s" if r["occurrences"] != 1 else ""}</span></div></div>' for r in rows)
    return f'<div class="lux-reg lux-reveal">{cards}</div><p class="lux-disclaimer">{_e(disclaimer)}</p>'


def restored_view(segments: List) -> str:
    body = "".join(f"<mark>{_e(t)}</mark>" if restored else _e(t) for t, restored in segments)
    return f'<div class="lux-card lux-restored">{body}</div>'


def posture(rows: List) -> str:
    out = []
    for ok, title, desc, value in rows:
        color = "var(--lux-green)" if ok is True else "var(--lux-yellow)" if ok is None else "var(--lux-red)"
        glyph = icon("check", 12) if ok is True else icon("alert", 12) if ok is None else icon("x", 12)
        out.append(f'<div class="row"><span class="st" style="--c:{color}">{glyph}</span>'
                   f'<div><b>{_e(title)}</b><span class="d">{_e(desc)}</span></div><span class="v">{_e(value)}</span></div>')
    return f'<div class="lux-card lux-posture">{"".join(out)}</div>'


def events(lines: List[str]) -> str:
    return f'<div class="lux-card lux-events">{_e(chr(10).join(lines))}</div>'


def login_card() -> str:
    return (f'<div class="lux-card lux-login"><div class="sb-mark" style="width:42px;height:42px">{icon("lock", 20)}</div>'
            f'<b>PII Gateway is locked</b><p>Enter the access passphrase to continue. Repeated failures lock this '
            f'client out with increasing delays.</p></div>')
