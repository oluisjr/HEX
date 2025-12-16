
# RGB(A) Color Picker
# Autor: LUIS IGNACIO JUNIOR
# ------------------------------------------------------------

from __future__ import annotations
import io
import re
import random
from typing import Tuple, Optional

import streamlit as st
from PIL import Image
import colorsys

# ----------------------------
# Configuração básica da página
# ----------------------------
st.set_page_config(
    page_title="Projeto RGBA",
    page_icon="🎨",
    layout="centered",
)

# ----------------------------
# Utilitários de conversão
# ----------------------------
HEX_REGEX = re.compile(r"^#([0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def clamp_int(x: int, lo: int = 0, hi: int = 255) -> int:
    """Restringe um inteiro ao intervalo [lo, hi]."""
    return max(lo, min(hi, int(x)))


def clamp_float(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Restringe um float ao intervalo [lo, hi]."""
    return max(lo, min(hi, float(x)))


def hex_to_rgba(hex_str: str) -> Tuple[int, int, int, float]:
    """
    Converte #RRGGBB ou #RRGGBBAA (AA em [00..FF]) para (R, G, B, A_float).
    Transparência A retorna em [0.0..1.0].
    Levanta ValueError se o formato for inválido.
    """
    if not HEX_REGEX.match(hex_str):
        raise ValueError("Hex inválido. Use #RRGGBB ou #RRGGBBAA.")
    hex_str = hex_str.lower()
    r = int(hex_str[1:3], 16)
    g = int(hex_str[3:5], 16)
    b = int(hex_str[5:7], 16)
    if len(hex_str) == 9:  # #RRGGBBAA
        a = int(hex_str[7:9], 16) / 255.0
    else:
        a = 1.0
    return r, g, b, a


def rgba_to_hex(r: int, g: int, b: int, a: float, with_alpha: bool = True) -> str:
    """
    Converte RGBA em #RRGGBB ou #RRGGBBAA.
    """
    r, g, b = clamp_int(r), clamp_int(g), clamp_int(b)
    a = clamp_float(a)
    if with_alpha:
        return f"#{r:02x}{g:02x}{b:02x}{int(round(a * 255)):02x}"
    return f"#{r:02x}{g:02x}{b:02x}"


def rgb_to_hsl(r: int, g: int, b: int) -> Tuple[float, float, float]:
    """
    Converte RGB(0..255) para HSL (H em [0..360], S e L em [0..1]).
    Usa colorsys (que trabalha com HLS), ajustando para HSL.
    """
    r_n, g_n, b_n = r / 255.0, g / 255.0, b / 255.0
    h, l, s_hls = colorsys.rgb_to_hls(r_n, g_n, b_n)
    # colorsys: HLS (Hue, Lightness, Saturation)
    # Para HSL, usamos o mesmo H e L; S do HLS é próximo ao S do HSL em muitas libs,
    # mas para consistência simples, retornamos (h*360, s_hls, l).
    return h * 360.0, s_hls, l


def rgb_to_hsv(r: int, g: int, b: int) -> Tuple[float, float, float]:
    """
    Converte RGB(0..255) para HSV (H em [0..360], S e V em [0..1]).
    """
    r_n, g_n, b_n = r / 255.0, g / 255.0, b / 255.0
    h, s, v = colorsys.rgb_to_hsv(r_n, g_n, b_n)
    return h * 360.0, s, v


def format_rgba(r: int, g: int, b: int, a: float) -> str:
    """Formata RGBA como string CSS."""
    return f"rgba({r}, {g}, {b}, {a:.1f})"


def format_rgb(r: int, g: int, b: int) -> str:
    """Formata RGB como string CSS."""
    return f"rgb({r}, {g}, {b})"


def format_hsl(h: float, s: float, l: float, a: Optional[float] = None) -> str:
    """Formata HSL/HSLA como string CSS (s, l em [%])."""
    s_pct = f"{s * 100:.2f}%"
    l_pct = f"{l * 100:.2f}%"
    h_deg = f"{h:.2f}"
    if a is None:
        return f"hsl({h_deg}, {s_pct}, {l_pct})"
    return f"hsla({h_deg}, {s_pct}, {l_pct}, {a:.1f})"


def format_hsv(h: float, s: float, v: float) -> str:
    """Formata HSV (não padrão CSS, mas útil para exibir)."""
    s_pct = f"{s * 100:.2f}%"
    v_pct = f"{v * 100:.2f}%"
    return f"hsv({h:.2f}, {s_pct}, {v_pct})"


def hsv_to_rgb(h: float, s: float, v: float) -> Tuple[int, int, int]:
    """
    Converte HSV (H em [0..360], S e V em [0..1]) para RGB (0..255).
    """
    import colorsys
    r_f, g_f, b_f = colorsys.hsv_to_rgb(h / 360.0, s, v)
    return int(round(r_f * 255)), int(round(g_f * 255)), int(round(b_f * 255))

# ----------------------------
# Renderização de preview
# ----------------------------

def render_preview(r: int, g: int, b: int, a: float, background_style: str = "gradient") -> None:
    """
    Mostra um retângulo de preview com fundo configurável e overlay da cor escolhida.
    background_style: "gradient" | "solid-light" | "solid-dark"
    """
    rgba_css = f"rgba({r}, {g}, {b}, {a:.3f})"

    if background_style == "solid-light":
        bg_css = "background: #ffffff;"
    elif background_style == "solid-dark":
        bg_css = "background: #121212;"
    else:
        # Gradient suave – DUAS camadas discretas
        bg_css = (
            "background:"
            " linear-gradient(135deg, rgba(255,255,255,0.10), rgba(255,255,255,0.02)) 0 0 / 100% 100%,"
            " linear-gradient(45deg,  rgba(0,0,0,0.08),  rgba(0,0,0,0.02)) 0 0 / 100% 100%;"
        )

    html = f"""
<div style="
    width: 280px;
    height: 140px;
    border-radius: 8px;
    overflow: hidden;
    {bg_css}
    position: relative;
    box-shadow: inset 0 0 0 1px rgba(0,0,0,0.10);
">
  <div style="
      position: absolute; inset: 0;
      background: {rgba_css};
  "></div>
</div>
"""
    st.markdown(html, unsafe_allow_html=True)


def show_codes(r: int, g: int, b: int, a: float, Key_prefix: str = "codes1") -> None:
    """Exibe códigos nos formatos principais."""
    h_hsl, s_hsl, l_hsl = rgb_to_hsl(r, g, b)
    h_hsv, s_hsv, v_hsv = rgb_to_hsv(r, g, b)
    hex_with_a = rgba_to_hex(r, g, b, a, with_alpha=True)
    hex_no_a = rgba_to_hex(r, g, b, a, with_alpha=False)

    col1, col2 = st.columns(2)
    with col1:
        st.caption("HEX (#RRGGBB)")
        st.code(hex_no_a)
        st.caption("HEX com Alpha (#RRGGBBAA)")
        st.code(hex_with_a)
        st.caption("RGB")
        st.code(format_rgb(r, g, b))
        st.caption("RGBA")
        st.code(format_rgba(r, g, b, a))  # alpha com 1 casa
    with col2:
        st.caption("HSL")
        st.code(format_hsl(h_hsl, s_hsl, l_hsl))
        st.caption("HSLA")
        st.code(format_hsl(h_hsl, s_hsl, l_hsl, a))  # alpha com 1 casa
        st.caption("HSV")

# ----------------------------
# Páginas
# ----------------------------
def page_picker() -> None:
    """Página principal: Picker RGBA."""
    st.header("Picker (RGBA)")
    # O st.color_picker retorna uma string Hex (#RRGGBB)
    # Doc: https://docs.streamlit.io/develop/api-reference/widgets/st.color_picker
    # (Veja acima na análise)
    hex_value = st.color_picker("Escolha uma cor (Hex)", value="#ff0077")
    alpha = st.slider("Transparência (Alpha)", 0.0, 1.0, 0.85, 0.01)

    try:
        r, g, b, _ = hex_to_rgba(hex_value)
    except ValueError as e:
        st.error(str(e))
        return

    col_left, col_right = st.columns([1, 1])
    with col_left:
        st.subheader("Preview")
        render_preview(r, g, b, alpha)
    with col_right:
        st.subheader("Códigos")
        show_codes(r, g, b, alpha, Key_prefix="codes_preview")

    st.divider()
    st.subheader("Ajuste Manual")
    r = st.number_input("R (0-255)", min_value=0, max_value=255, value=r)
    g = st.number_input("G (0-255)", min_value=0, max_value=255, value=g)
    b = st.number_input("B (0-255)", min_value=0, max_value=255, value=b)
    alpha2 = st.slider("Alpha (0.0-1.0)", 0.0, 1.0, alpha, 0.01)
    st.write("Preview ajustado:")
    render_preview(r, g, b, alpha2)
    show_codes(r, g, b, alpha2, Key_prefix="codes_adjusted")


def page_converters() -> None:
    """Conversores: Hex → RGBA e RGBA → Hex."""
    st.header("Conversores")
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Hex → RGBA")
        hx = st.text_input("Hex (#RRGGBB ou #RRGGBBAA)", "#1a73e8ff")
        if st.button("Converter para RGBA", type="primary"):
            try:
                r, g, b, a = hex_to_rgba(hx)
                st.success(f"RGBA: {format_rgba(r, g, b, a)}")
                render_preview(r, g, b, a)
            except ValueError as e:
                st.error(str(e))

    with col2:
        st.subheader("RGBA → Hex")
        r = st.number_input("R", 0, 255, 26)
        g = st.number_input("G", 0, 255, 115)
        b = st.number_input("B", 0, 255, 232)
        a = st.slider("Alpha", 0.0, 1.0, 1.0, 0.01)
        with_alpha = st.checkbox("Incluir alpha no Hex (#RRGGBBAA)", value=True)
        if st.button("Converter para Hex"):
            hex_out = rgba_to_hex(r, g, b, a, with_alpha=with_alpha)
            st.success(f"Hex: {hex_out}")
            render_preview(r, g, b, a)

def page_wheel() -> None:
    """Roda de Cores (HSV) — interface distinta do Picker, sem st.color_picker."""
    st.header("Roda de Cores (HSV)")
    st.caption(
        "Selecione a cor pela **matiz (Hue)**, **saturação (S)** e **brilho (Value)**. "
        "Hue é o ângulo da roda (0–360°), Saturation é o raio (0–1) e Value é o brilho (0–1)."
    )

    # Controles HSV (a 'roda' em 2D + eixo de brilho)
    hue = st.slider("Matiz (Hue) — ângulo (°)", 0, 360, 0, step=1,
                    help="0=vermelho, 120=verde, 240=azul…")
    sat = st.slider("Saturação (S)", 0.0, 1.0, 1.0, 0.01,
                    help="0=cinza (sem cor), 1=cor totalmente saturada")
    val = st.slider("Brilho (V)", 0.0, 1.0, 1.0, 0.01,
                    help="0=preto, 1=claro")

    # Transparência independente
    alpha = st.slider("Transparência (Alpha)", 0.0, 1.0, 1.0, 0.1)

    # HSV -> RGB
    r, g, b = hsv_to_rgb(hue, sat, val)

    # Preview e códigos — keys únicas para evitar colisões
    st.subheader("Preview")
    render_preview(r, g, b, alpha, background_style="gradient")

    st.subheader("Códigos")
    show_codes(r, g, b, alpha, Key_prefix="wheel_hsv")

    # (Opcional) Paletas relacionadas usando a lógica de roda
    st.divider()
    st.subheader("Paletas relacionadas")
    colA, colB, colC = st.columns(3)

    # Complementar: Hue + 180°
    comp_hue = (hue + 180) % 360
    comp_r, comp_g, comp_b = hsv_to_rgb(comp_hue, sat, val)

    # Análogas: Hue ± 30°
    ana1_hue = (hue + 30) % 360
    ana2_hue = (hue - 30) % 360
    ana1_r, ana1_g, ana1_b = hsv_to_rgb(ana1_hue, sat, val)
    ana2_r, ana2_g, ana2_b = hsv_to_rgb(ana2_hue, sat, val)

    with colA:
        st.caption(f"Complementar ({comp_hue:.0f}°)")
        render_preview(comp_r, comp_g, comp_b, alpha, background_style="gradient")
        show_codes(comp_r, comp_g, comp_b, alpha, Key_prefix="wheel_comp")

    with colB:
        st.caption(f"Análoga +30° ({ana1_hue:.0f}°)")
        render_preview(ana1_r, ana1_g, ana1_b, alpha, background_style="gradient")
        show_codes(ana1_r, ana1_g, ana1_b, alpha, Key_prefix="wheel_ana1")

    with colC:
        st.caption(f"Análoga −30° ({ana2_hue:.0f}°)")
        render_preview(ana2_r, ana2_g, ana2_b, alpha, background_style="gradient")
        show_codes(ana2_r, ana2_g, ana2_b, alpha, Key_prefix="wheel_ana2")

def page_image() -> None:
    """Selecionar cor por pixel de imagem (por coordenadas)."""
    st.header("Picker por Imagem")
    st.caption("Faça upload da imagem e use os sliders para escolher (x, y).")
    file = st.file_uploader("Imagem (PNG/JPG)", type=["png", "jpg", "jpeg"])
    if not file:
        st.info("Envie uma imagem para começar.")
        return

    img = Image.open(file).convert("RGBA")
    w, h = img.size
    st.image(img, caption=f"Dimensões: {w}×{h}", use_container_width=True)

    x = st.slider("x", 0, w - 1, w // 2)
    y = st.slider("y", 0, h - 1, h // 2)

    r, g, b, a_byte = img.getpixel((x, y))
    a = a_byte / 255.0

    st.write(f"Pixel @ ({x}, {y})")
    render_preview(r, g, b, a)
    show_codes(r, g, b, a)


def page_random() -> None:
    """Geração de cor aleatória."""
    st.header("Cor Aleatória")
    st.caption("Gera uma cor e exibe em múltiplos formatos (como no gerador do site).")
    if st.button("Gerar"):
        r, g, b = random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)
        a = 1.0
        render_preview(r, g, b, a)
        show_codes(r, g, b, a)


# ----------------------------
# Navegação simples por tabs
# ----------------------------
tabs = st.tabs(["Picker", "Conversores", "Roda"])

with tabs[0]:
    page_picker()
with tabs[1]:
    page_converters()
with tabs[2]:

    page_wheel()


