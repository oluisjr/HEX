
# RGB(A) Color Picker
# Autor: LUIS IGNACIO JUNIOR
# ------------------------------------------------------------

import streamlit as st
from PIL import Image
import io
import re
import random
import colorsys
import datetime
from typing import Tuple, Optional

image = "microsoft-power-apps.jpg"

# ------------------------------------------------------------
# 1. CONFIGURAÇÃO DA PÁGINA
# ------------------------------------------------------------
st.set_page_config(
    page_title="Power Apps Docs & Tools",
    page_icon="📘",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ------------------------------------------------------------
# 2. CSS CUSTOMIZADO (Visual Compacto & Adaptive Cards)
# ------------------------------------------------------------
st.markdown("""
    <style>
    /* Fonte estilo Segoe UI (Padrão Microsoft) */
    html, body, [class*="css"] {
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        color: #323130;
    }
    
    /* --- SIDEBAR COMPACTA --- */
    [data-testid="stSidebar"] {
        background-color: #ffffff;
        border-right: 1px solid #e1dfdd;
    }
    /* Remove padding excessivo entre botões */
    [data-testid="stSidebar"] .stButton {
        margin-bottom: -12px;
    }
    [data-testid="stSidebar"] button {
        padding: 6px 10px !important;
        height: auto !important;
        border: none;
        text-align: left;
        width: 100%;
        background: transparent;
        color: #323130;
        font-size: 14px;
        font-weight: 400;
    }
    [data-testid="stSidebar"] button:hover {
        background-color: #f3f2f1;
        color: #0078d4;
        font-weight: 600;
    }
    
    /* --- ADAPTIVE CARDS STYLE --- */
    .example-card {
        background-color: #ffffff;
        border: 1px solid #e1dfdd;
        border-radius: 4px;
        padding: 15px;
        margin-bottom: 20px;
        box-shadow: 0 1.6px 3.6px 0 rgba(0,0,0,0.132), 0 0.3px 0.9px 0 rgba(0,0,0,0.108);
    }
    .card-title {
        font-weight: 600;
        color: #0078d4;
        margin-bottom: 5px;
        border-bottom: 1px solid #e1dfdd;
        padding-bottom: 5px;
    }
    .prop-label {
        font-size: 12px;
        color: #605e5c;
        font-weight: 700;
        margin-top: 10px;
    }
    </style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------
# 3. LÓGICA DAS FERRAMENTAS (CÓDIGO ORIGINAL PRESERVADO)
# ------------------------------------------------------------

HEX_REGEX = re.compile(r"^#([0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")

def clamp_int(x: int, lo: int = 0, hi: int = 255) -> int:
    return max(lo, min(hi, int(x)))

def clamp_float(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(x)))

def hex_to_rgba(hex_str: str) -> Tuple[int, int, int, float]:
    if not HEX_REGEX.match(hex_str):
        raise ValueError("Hex inválido.")
    hex_str = hex_str.lower()
    r = int(hex_str[1:3], 16)
    g = int(hex_str[3:5], 16)
    b = int(hex_str[5:7], 16)
    if len(hex_str) == 9:
        a = int(hex_str[7:9], 16) / 255.0
    else:
        a = 1.0
    return r, g, b, a

def rgba_to_hex(r: int, g: int, b: int, a: float, with_alpha: bool = True) -> str:
    r, g, b = clamp_int(r), clamp_int(g), clamp_int(b)
    a = clamp_float(a)
    if with_alpha:
        return f"#{r:02x}{g:02x}{b:02x}{int(round(a * 255)):02x}"
    return f"#{r:02x}{g:02x}{b:02x}"

def rgb_to_hsl(r: int, g: int, b: int) -> Tuple[float, float, float]:
    r_n, g_n, b_n = r / 255.0, g / 255.0, b / 255.0
    h, l, s_hls = colorsys.rgb_to_hls(r_n, g_n, b_n)
    return h * 360.0, s_hls, l

def rgb_to_hsv(r: int, g: int, b: int) -> Tuple[float, float, float]:
    r_n, g_n, b_n = r / 255.0, g / 255.0, b / 255.0
    h, s, v = colorsys.rgb_to_hsv(r_n, g_n, b_n)
    return h * 360.0, s, v

def format_rgba(r: int, g: int, b: int, a: float) -> str:
    return f"rgba({r}, {g}, {b}, {a:.1f})"

def format_rgb(r: int, g: int, b: int) -> str:
    return f"rgb({r}, {g}, {b})"

def format_hsl(h: float, s: float, l: float, a: Optional[float] = None) -> str:
    s_pct = f"{s * 100:.2f}%"
    l_pct = f"{l * 100:.2f}%"
    h_deg = f"{h:.2f}"
    if a is None:
        return f"hsl({h_deg}, {s_pct}, {l_pct})"
    return f"hsla({h_deg}, {s_pct}, {l_pct}, {a:.1f})"

def format_hsv(h: float, s: float, v: float) -> str:
    s_pct = f"{s * 100:.2f}%"
    v_pct = f"{v * 100:.2f}%"
    return f"hsv({h:.2f}, {s_pct}, {v_pct})"

def hsv_to_rgb(h: float, s: float, v: float) -> Tuple[int, int, int]:
    r_f, g_f, b_f = colorsys.hsv_to_rgb(h / 360.0, s, v)
    return int(round(r_f * 255)), int(round(g_f * 255)), int(round(b_f * 255))

def render_preview(r: int, g: int, b: int, a: float, background_style: str = "gradient") -> None:
    rgba_css = f"rgba({r}, {g}, {b}, {a:.3f})"
    if background_style == "solid-light":
        bg_css = "background: #ffffff;"
    elif background_style == "solid-dark":
        bg_css = "background: #121212;"
    else:
        bg_css = (
            "background:"
            " linear-gradient(135deg, rgba(255,255,255,0.10), rgba(255,255,255,0.02)) 0 0 / 100% 100%,"
            " linear-gradient(45deg,  rgba(0,0,0,0.08),  rgba(0,0,0,0.02)) 0 0 / 100% 100%;"
        )
    html = f"""<div style="width: 280px; height: 140px; border-radius: 8px; overflow: hidden; {bg_css} position: relative; box-shadow: inset 0 0 0 1px rgba(0,0,0,0.10);"><div style="position: absolute; inset: 0; background: {rgba_css};"></div></div>"""
    st.markdown(html, unsafe_allow_html=True)

def show_codes(r: int, g: int, b: int, a: float, Key_prefix: str = "codes1") -> None:
    h_hsl, s_hsl, l_hsl = rgb_to_hsl(r, g, b)
    h_hsv, s_hsv, v_hsv = rgb_to_hsv(r, g, b)
    hex_with_a = rgba_to_hex(r, g, b, a, with_alpha=True)
    hex_no_a = rgba_to_hex(r, g, b, a, with_alpha=False)
    col1, col2 = st.columns(2)
    with col1:
        st.caption("HEX (#RRGGBB)")
        st.code(hex_no_a)
        st.caption("HSL")
        st.code(format_hsl(h_hsl, s_hsl, l_hsl))
        st.caption("RGB")
        st.code(format_rgb(r, g, b))
        st.caption("HSV")
        st.code(format_hsv(h_hsv, s_hsv, v_hsv))
    with col2:
        st.caption("HEX com Alpha (#RRGGBBAA)")
        st.code(hex_with_a)
        st.caption("HSLA")
        st.code(format_hsl(h_hsl, s_hsl, l_hsl, a))
        st.caption("RGBA")
        st.code(format_rgba(r, g, b, a))
        st.caption("Power Apps Formula")
        st.code(f"RGBA({r}, {g}, {b}, {a:.1f})", language="powerapps")

# --- FUNÇÕES DAS FERRAMENTAS ORIGINAIS ---
def page_picker() -> None:
    st.header("Picker (RGBA)")
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
    r = st.number_input("R (0-255)", 0, 255, r)
    g = st.number_input("G (0-255)", 0, 255, g)
    b = st.number_input("B (0-255)", 0, 255, b)
    alpha2 = st.slider("Alpha (0.0-1.0)", 0.0, 1.0, alpha, 0.01)
    st.write("Preview ajustado:")
    render_preview(r, g, b, alpha2)
    show_codes(r, g, b, alpha2, Key_prefix="codes_adjusted")

def page_converters() -> None:
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
        with_alpha = st.checkbox("Incluir alpha no Hex", value=True)
        if st.button("Converter para Hex"):
            hex_out = rgba_to_hex(r, g, b, a, with_alpha=with_alpha)
            st.success(f"Hex: {hex_out}")
            render_preview(r, g, b, a)

def page_wheel() -> None:
    st.header("Roda de Cores (HSV)")
    hue = st.slider("Matiz (Hue)", 0, 360, 0, 1)
    sat = st.slider("Saturação (S)", 0.0, 1.0, 1.0, 0.01)
    val = st.slider("Brilho (V)", 0.0, 1.0, 1.0, 0.01)
    alpha = st.slider("Alpha", 0.0, 1.0, 1.0, 0.1)
    r, g, b = hsv_to_rgb(hue, sat, val)
    st.subheader("Preview")
    render_preview(r, g, b, alpha, "gradient")
    st.subheader("Códigos")
    show_codes(r, g, b, alpha, "wheel_hsv")
    st.divider()
    st.subheader("Paletas relacionadas")
    colA, colB, colC = st.columns(3)
    comp_r, comp_g, comp_b = hsv_to_rgb((hue+180)%360, sat, val)
    ana1_r, ana1_g, ana1_b = hsv_to_rgb((hue+30)%360, sat, val)
    ana2_r, ana2_g, ana2_b = hsv_to_rgb((hue-30)%360, sat, val)
    with colA:
        st.caption("Complementar")
        render_preview(comp_r, comp_g, comp_b, alpha)
        show_codes(comp_r, comp_g, comp_b, alpha, "comp_color")
    with colB:
        st.caption("Análoga +30°")
        render_preview(ana1_r, ana1_g, ana1_b, alpha)
        show_codes(ana1_r, ana1_g, ana1_b, alpha, "ana1_color")
    with colC:
        st.caption("Análoga -30°")
        render_preview(ana2_r, ana2_g, ana2_b, alpha)
        show_codes(ana2_r, ana2_g, ana2_b, alpha, "ana2_color")

def page_image() -> None:
    st.header("Picker por Imagem")
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
    st.header("Cor Aleatória")
    if st.button("Gerar"):
        r, g, b = random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)
        a = 1.0
        render_preview(r, g, b, a)
        show_codes(r, g, b, a)


# ------------------------------------------------------------
# 4. CONTEÚDO DE DOCUMENTAÇÃO (POWER APPS)
# ------------------------------------------------------------

def show_home():
    st.title("Bem-vindo ao Treinamento de Power Apps")
    st.markdown("""
    Esta documentação interativa permite que você teste os conceitos em tempo real.
    
    > **Como usar:**
    > 1. Use o menu lateral para navegar entre os Laboratórios.
    > 2. Altere os valores (sliders, textos) para ver o código Power FX sendo gerado.
    > 3. Copie o código gerado direto para o seu App.
    """)

    st.divider()

# --- Helper de Visualização ---
def card_header(title, desc):
    st.markdown(f"""
    <div style="margin-bottom:10px;">
        <span style="font-size:18px; font-weight:600; color:#0078d4;">{title}</span>
        <br><span style="font-size:13px; color:#605e5c;">{desc}</span>
    </div>""", unsafe_allow_html=True)

def show_controls():
    st.header("🎛️ Laboratório de Controles")
    st.markdown("Experimente as configurações dos controles mais usados.")

    # Abas expandidas para cobrir mais controles
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Inputs Básicos", "Seleção", "Datas", "Galerias", "Botões"])

    # 1. Inputs Básicos
    with tab1:
        card_header("Text Input", "O controle padrão para digitação.")
        c1, c2 = st.columns([1, 1.5])
        with c1:
            st.markdown("**Configurações:**")
            def_text = st.text_input("Default (Valor Inicial)", "Texto Exemplo")
            hint_text = st.text_input("HintText (Dica)", "Digite seu nome...")
            mode_sel = st.selectbox("Mode", ["TextMode.SingleLine", "TextMode.MultiLine", "TextMode.Password"])
        with c2:
            st.markdown("###### Preview Simulado")
            # Simula HTML
            if "Password" in mode_sel:
                inp_type = "password"
            else:
                inp_type = "text"
            
            st.markdown(f"""
            <input type="{inp_type}" value="{def_text}" placeholder="{hint_text}" 
            style="width:100%; padding:8px; border:1px solid #ccc; border-radius:4px;">
            """, unsafe_allow_html=True)
            
            st.code(f"""
            TextInput1.Default = "{def_text}"
            TextInput1.HintText = "{hint_text}"
            TextInput1.Mode = {mode_sel}
            """, language="powerapps")

    # 2. Seleção
    with tab2:
        card_header("Dropdown & Radio", "Forçar o usuário a escolher uma opção válida.")
        c1, c2 = st.columns([1, 1.5])
        with c1:
            control_type = st.radio("Tipo de Controle", ["Dropdown", "Radio Button", "Toggle"], horizontal=True)
            items_str = st.text_input("Items (separados por vírgula)", "Alta, Média, Baixa")
            
            # CORREÇÃO 1: Tratamento seguro da lista para evitar IndexError
            if items_str.strip():
                items_list = [x.strip() for x in items_str.split(",")]
            else:
                items_list = ["Opção 1"] # Fallback para não quebrar
            
            # Formata a lista para string do Power Apps: ["A", "B"]
            formatted_list_code = '", "'.join(items_list)
            
        with c2:
            st.markdown("###### Preview")
            if control_type == "Dropdown":
                st.selectbox("Simulação Dropdown", items_list)
                st.code(f'Dropdown1.Items = ["{formatted_list_code}"]', language="powerapps")
            elif control_type == "Radio Button":
                st.radio("Simulação Radio", items_list)
                st.code(f'Radio1.Items = ["{formatted_list_code}"]', language="powerapps")
            else:
                st.checkbox("Toggle (Simulação)", value=True)
                st.code(f'Toggle1.Default = true', language="powerapps")

    # 3. Datas
    with tab3:
        card_header("Date Picker", "Seleção de datas segura.")
        c1, c2 = st.columns([1, 1.5])
        with c1:
            dt_val = st.date_input("DefaultDate", datetime.date.today())
            fmt = st.selectbox("Format", ["DateTimeFormat.ShortDate", "DateTimeFormat.LongDate"])
        with c2:
            # CORREÇÃO 2: Formatação condicional para exibir diferença entre Short e Long Date
            if "LongDate" in fmt:
                # Gambiarra segura para simular formato longo em PT-BR sem depender de locale do sistema
                meses = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", 
                         "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
                long_date_str = f"{dt_val.day} de {meses[dt_val.month-1]} de {dt_val.year}"
                st.markdown(f"Data Selecionada (Long): **{long_date_str}**")
            else:
                st.markdown(f"Data Selecionada (Short): **{dt_val.strftime('%d/%m/%Y')}**")

            st.code(f"""
            DatePicker1.DefaultDate = Date({dt_val.year}, {dt_val.month}, {dt_val.day})
            DatePicker1.Format = {fmt}
            """, language="powerapps")

    # 4. Galerias (Simulador Visual)
    with tab4:
            card_header("Gallery (Vertical)", "Visualização de como dados repetidos aparecem.")
            
            st.markdown("**Configurações da Galeria:**")
            
            col_conf1, col_conf2 = st.columns(2)
            with col_conf1:
                data_count = st.slider("Quantidade de Itens", 1, 10, 3)
            with col_conf2:
                # --- 1. SLIDER PARA CONTROLAR O TEMPLATE SIZE ---
                tamanho_template = st.slider("TemplateSize (Altura do Item)", 50, 150, 80)
            
            # Gera o HTML repetido para simular a galeria
            html_items = ""
            for i in range(1, data_count + 1):
                # --- 2. APLICANDO A ALTURA DINÂMICA NO HTML (height) ---
                html_items += f"""<div style="border:1px solid #ddd; height:{tamanho_template}px; padding:10px; margin-bottom:5px; display:flex; align-items:center; background:white; box-sizing: border-box;">
                    <div style="width:40px; height:40px; background:#0078d4; border-radius:50%; color:white; display:flex; justify-content:center; align-items:center; margin-right:10px; flex-shrink:0;">
                        {i}
                    </div>
                    <div style="overflow:hidden;">
                        <div style="font-weight:bold;">Título do Item {i}</div>
                        <div style="font-size:12px; color:#666;">Subtítulo ou Descrição...</div>
                    </div>
                    <div style="margin-left:auto;">></div>
                </div>"""
            
            # --- 3. CORREÇÃO DA INDENTAÇÃO (Para o HTML renderizar e não aparecer texto cru) ---
            # Note que o HTML abaixo está colado na margem esquerda, sem espaços antes.
            st.markdown(f"""
            <div style="background:#f0f0f0; padding:10px; height:300px; overflow-y:auto; border:1px solid #999;">
            {html_items}
            </div>
            """, unsafe_allow_html=True)
            
            # --- 4. CÓDIGO DINÂMICO ---
            st.info("O código abaixo reflete as configurações acima:")
            st.code(f"""
            Gallery1.Items = colMeusDados
            Gallery1.TemplateSize = {tamanho_template}  // Valor dinâmico baseado no slider
            """, language="powerapps")

    # 5. Botões
    with tab5:
        card_header("Button & Styling", "Personalização visual completa.")
        c1, c2 = st.columns([1, 1.5])
        with c1:
            txt_btn = st.text_input("Text", "Enviar", key="btn_txt_2")
            # Usando nome consistente de variável
            fill_color = st.color_picker("Fill", "#0078D4", key="btn_fill_2")
            radius = st.slider("BorderRadius", 0, 50, 4)
            is_disabled = st.checkbox("Desabilitado (DisplayMode.Disabled)", value=False)
            
        with c2:
            # Lógica de simulação visual
            opacity = "0.5" if is_disabled else "1.0"
            cursor = "not-allowed" if is_disabled else "pointer"
            code_display_mode = "DisplayMode.Disabled" if is_disabled else "DisplayMode.Edit"

            # CORREÇÃO 1: Removida a indentação do HTML para renderizar corretamente
            st.markdown(f"""
<button style="
background:{fill_color}; 
color:white; 
border:none; 
padding:20px 44px;
border-radius:{radius}px;
opacity:{opacity};
cursor:{cursor};
">
{txt_btn}
</button>
""", unsafe_allow_html=True)
            
            st.code(f"""
Button1.Text = "{txt_btn}"
Button1.Fill = ColorValue("{fill_color}")
Button1.RadiusTopLeft = {radius}
Button1.RadiusTopRight = {radius}
Button1.RadiusBottomLeft = {radius}
Button1.RadiusBottomRight = {radius}
Button1.DisplayMode = {code_display_mode}
""", language="powerapps")

def show_formulas():
    st.header("∑ Laboratório de Fórmulas")
    
    tab1, tab2, tab3 = st.tabs(["Gerador de Patch (CRUD)", "Datas & Tempo", "Lógica"])

    # 1. Gerador de Patch
    with tab1:
        card_header("Gerador de Patch", "Preencha os campos para gerar o código de salvamento.")
        
        col_db = st.text_input("Nome da Fonte de Dados", "Funcionarios_TB")
        f_nome = st.text_input("Campo: Nome", "TextInput_Nome.Text")
        f_cargo = st.text_input("Campo: Cargo", "Dropdown_Cargo.Selected.Value")
        f_idade = st.text_input("Campo: Idade", "Value(TextInput_Idade.Text)")
        
        modo = st.radio("Ação", ["Criar Novo (Defaults)", "Editar (Lookup/Gallery)"], horizontal=True)
        
        if "Criar" in modo:
            record_part = f"Defaults({col_db})"
        else:
            record_part = "Gallery1.Selected"
            
        st.subheader("Código Gerado:")
        st.code(f"""
        Patch(
            {col_db},
            {record_part},
            {{
                Nome: {f_nome},
                Cargo: {f_cargo},
                Idade: {f_idade},
                DataRegistro: Now()
            }}
        )
        """, language="powerapps")

    # 2. Datas e Tempo
    with tab2:
        card_header("Manipulação de Datas", "DateAdd, DateDiff e Formatação.")
        
        d_base = st.date_input("Data Base", datetime.date.today())
        d_add = st.number_input("Dias para adicionar (DateAdd)", value=5)
        
        d_result = d_base + datetime.timedelta(days=d_add)
        
        st.write(f"Resultado: **{d_result.strftime('%d/%m/%Y')}**")
        
        st.code(f"""
        // Adicionar dias
        DateAdd(Date({d_base.year}, {d_base.month}, {d_base.day}), {d_add}, TimeUnit.Days)

        // Formatar para Texto
        Text(Now(), "dd/mm/yyyy hh:mm")
        """, language="powerapps")

    # 3. Lógica
    with tab3:
        st.markdown("**Round & RoundUp**")
        val_float = st.number_input("Valor Decimal", value=12.345, format="%.3f")
        casas = st.slider("Casas Decimais", 0, 4, 1)
        
        st.write(f"Round: {round(val_float, casas)}")
        st.code(f"Round({val_float}, {casas})", language="powerapps")


def show_connectors():
    st.header("🔌 Conectores Suportados")
    st.markdown("Lista categorizada para consulta rápida.")

    tab1, tab2 = st.tabs(["Standard (Gratuitos)", "Premium (Pagos)"])

    with tab1:
        st.success("✅ **Inclusos na licença Microsoft 365 Business/Enterprise**")
        st.markdown("""
        | Conector | Uso Principal | Limitações |
        | :--- | :--- | :--- |
        | **SharePoint Online** | Listas como tabelas de dados. | Delegação limitada a 2k itens. Não relacional. |
        | **Office 365 Users** | Pegar foto, email, departamento do usuário. | Nenhuma. Essencial em todo app. |
        | **Outlook.com / 365** | Enviar emails, ler calendário. | Limite de envio de emails p/ minuto. |
        | **OneDrive (Business)** | Ler arquivos Excel/PDF. | Excel como banco de dados é **instável**. Evite. |
        | **Microsoft Planner** | Criar tarefas e buckets kanban. | Bom para gestão de atividades simples. |
        | **Microsoft Teams** | Postar em canais, Deep Linking. | Integração nativa. |
        | **RSS** | Ler notícias externas. | Apenas leitura. |
        """)

    with tab2:
        st.warning("💲 **Requer licença 'Per App'  ou 'Per User'**")
        st.markdown("""
        | Conector | Uso Principal | Vantagens |
        | :--- | :--- | :--- |
        | **Microsoft Dataverse** | Banco oficial da Power Platform. | Segurança hierárquica, Relacionamentos complexos, ALM. |
        | **SQL Server** | Bancos legados ou Azure SQL. | Robustez, Delegação quase total. |
        | **HTTP / Web Request** | Consumir APIs (JSON/REST). | Conecta com QUALQUER sistema moderno. |
        | **Salesforce** | Dados de CRM. | Leitura/Escrita direta no CRM. |
        | **Oracle DB** | Bancos Oracle on-premise. | Requer Gateway de Dados. |
        | **Adobe PDF Services** | Manipulação avançada de PDF. | Criar/Juntar PDFs profissionalmente. |
        | **Docusign** | Assinatura digital. | Enviar envelopes para assinar. |
        """)

def show_variables():
    st.header("📦 Variáveis na Prática")
    
    st.markdown("""
    Veja a diferença visual entre **Global (Set)** e **Local (UpdateContext)**.
    """)

    c1, c2 = st.columns(2)
    
    with c1:
        st.subheader("UpdateContext (Local)")
        st.markdown("*Use para: Popups, Toggles, Loading de Tela.*")
        
        # Simulação de State Local
        if 'ctx_popup' not in st.session_state: st.session_state.ctx_popup = False
        
        if st.button("Alternar 'locPopup'"):
            st.session_state.ctx_popup = not st.session_state.ctx_popup
            
        if st.session_state.ctx_popup:
            st.info("🟦 **TRUE**: O Popup está visível!")
        else:
            st.write("⬜ **FALSE**: O Popup está oculto.")
            
        st.code(f"""
        UpdateContext({{ locPopup: !locPopup }})
        // Valor Atual: {str(st.session_state.ctx_popup).lower()}
        """, language="powerapps")

    with c2:
        st.subheader("Set (Global)")
        st.markdown("*Use para: Usuário Logado, Configs, Dados entre telas.*")
        
        user_input = st.text_input("Definir Nome do Usuário", "Maria")
        
        if st.button("Set(gblUser, ...)", type="primary"):
            st.session_state.gbl_user = user_input
            st.success(f"Variável gblUser definida para: {user_input}")
            
        st.code(f"""
        Set(gblUser, "{st.session_state.get('gbl_user', '')}")
        // Esta variável pode ser lida na Tela 1, Tela 2, Tela 50...
        """, language="powerapps")

    st.divider()
    st.subheader("Collections (Tabelas)")
    if st.button("Adicionar Item à Coleção"):
        if 'my_col' not in st.session_state: st.session_state.my_col = []
        st.session_state.my_col.append({"Item": f"Prod {len(st.session_state.my_col)+1}", "Valor": random.randint(10,99)})
    
    if st.button("Limpar Coleção"):
        st.session_state.my_col = []
        
    st.table(st.session_state.get('my_col', []))
    st.code("Collect(colCarrinho, {Item: '...', Valor: ...})", language="powerapps")

# ------------------------------------------------------------
# 5. NAVEGAÇÃO LATERAL
# ------------------------------------------------------------

st.sidebar.title("Docs & Tools")

if 'section' not in st.session_state: st.session_state.section = "Documentação"
if 'page' not in st.session_state: st.session_state.page = "Início"

# Menu 1
with st.sidebar.expander("🟣 POWER APPS", expanded=True):
    if st.button("🏠 Início"): 
        st.session_state.section = "Documentação"
        st.session_state.page = "Início"
    if st.button("🎛️ Laboratório de Controles"):
        st.session_state.section = "Documentação"
        st.session_state.page = "Controles"
    if st.button("∑ Laboratório de Fórmulas"):
        st.session_state.section = "Documentação"
        st.session_state.page = "Fórmulas"
    if st.button("🔌 Conectores (Lista)"):
        st.session_state.section = "Documentação"
        st.session_state.page = "Conectores"
    if st.button("📦 Variáveis (Demo)"):
        st.session_state.section = "Documentação"
        st.session_state.page = "Variáveis"
    if st.button("🎨 Color Picker RGBA"):
        st.session_state.section = "Ferramentas"
        st.session_state.page = "Picker"
    if st.button("🔄 Conversores Hex/RGB"):
        st.session_state.section = "Ferramentas"
        st.session_state.page = "Conversores"
    if st.button("🎡 Roda de Cores (HSV)"):
        st.session_state.section = "Ferramentas"
        st.session_state.page = "Roda"
    if st.button("🎲 Cor Aleatória"):
        st.session_state.section = "Ferramentas"
        st.session_state.page = "Aleatorio"

st.sidebar.caption("Desenvolvido por Lulinha")

# Roteamento
if st.session_state.section == "Documentação":
    if st.session_state.page == "Início": show_home()
    elif st.session_state.page == "Controles": show_controls()
    elif st.session_state.page == "Fórmulas": show_formulas()
    elif st.session_state.page == "Conectores": show_connectors()
    elif st.session_state.page == "Variáveis": show_variables()

elif st.session_state.section == "Ferramentas":
    if st.session_state.page == "Picker": page_picker()
    elif st.session_state.page == "Conversores": page_converters()
    elif st.session_state.page == "Roda": page_wheel()
    elif st.session_state.page == "Imagem": page_image()
    elif st.session_state.page == "Aleatorio": page_random()



