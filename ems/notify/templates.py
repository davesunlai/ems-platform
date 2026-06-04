"""HTML šablony e-mailů TERA EMS."""
from __future__ import annotations


def html_mail(heading: str, paragraphs: list[str], button_label: str,
              link: str, note: str) -> str:
    ps = "".join(
        f'<p style="margin:0 0 14px;color:#cfd6e4;font-size:15px;line-height:1.55">{p}</p>'
        for p in paragraphs
    )
    return (
        '<!DOCTYPE html><html><body style="margin:0;background:#0d1117;padding:24px;'
        'font-family:Segoe UI,Roboto,Helvetica,Arial,sans-serif">'
        '<div style="max-width:520px;margin:0 auto;background:#161b22;border:1px solid '
        '#30363d;border-radius:12px;overflow:hidden">'
        '<div style="padding:18px 28px;border-bottom:1px solid #30363d">'
        '<span style="font-size:18px;font-weight:700;color:#3fb950;letter-spacing:.5px">'
        'TERA<span style="color:#e6edf3"> EMS</span></span></div>'
        '<div style="padding:24px 28px">'
        f'<h1 style="margin:0 0 16px;font-size:20px;color:#e6edf3">{heading}</h1>'
        f'{ps}'
        '<div style="text-align:center;margin:26px 0">'
        f'<a href="{link}" style="display:inline-block;background:#238636;color:#ffffff;'
        'text-decoration:none;padding:12px 30px;border-radius:8px;font-weight:600;'
        f'font-size:15px">{button_label}</a></div>'
        f'<p style="margin:0;color:#8b949e;font-size:13px;line-height:1.5">{note}</p>'
        '<p style="margin:14px 0 0;color:#6e7681;font-size:12px;word-break:break-all">'
        f'Pokud tlačítko nefunguje, použijte odkaz: {link}</p></div>'
        '<div style="padding:14px 28px;border-top:1px solid #30363d;color:#6e7681;'
        'font-size:12px">TERA EMS · energetický management</div>'
        '</div></body></html>'
    )
