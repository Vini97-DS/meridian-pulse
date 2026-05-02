import streamlit as st
from supabase import create_client, Client
import pandas as pd
from datetime import datetime, timedelta, time

# 1. CONEXÃO COM SUPABASE
@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"].strip("/")
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

try:
    supabase = init_connection()
except Exception as e:
    st.error(f"Erro Crítico de Conexão: {e}")
    st.stop()

# 2. UX & UI CUSTOMIZADA (PADRÃO MERIDIAN)
# MELHORIA 1: Adicionado parâmetro logo_url — renderiza o logo no topo via HTML se informado
def apply_custom_style(primary_color="#0D1B2E", secondary_color="#C5A059", text_color="#FFFFFF", logo_url=None):
    logo_html = f'<img src="{logo_url}" style="height:60px; margin-bottom:1rem; display:block;">' if logo_url else ""
    st.markdown(f"""
        <style>
        .stApp, [data-testid="stHeader"] {{ background-color: {primary_color} !important; }}
        [data-testid="stHeader"] button {{ color: {secondary_color} !important; background-color: rgba(255, 255, 255, 0.1); border-radius: 50%; }}
        [data-testid="stSidebar"] {{ background-color: #050b14 !important; border-right: 1px solid {secondary_color}; }}
        h1, h2, h3, p, label, [data-testid="stMetricValue"], .stMarkdown {{ color: {text_color} !important; }}
        div.stButton > button {{ background-color: {secondary_color} !important; color: {primary_color} !important; border-radius: 6px; font-weight: bold; height: 3em; border: none; }}
        footer {{visibility: hidden;}}
        header {{visibility: block !important;}}
        </style>
        {logo_html}
    """, unsafe_allow_html=True)

# 3. LÓGICA DE SLOTS (OCULTA OCUPADOS)
# MELHORIA 2: Busca duração de cada agendamento existente e bloqueia
def get_available_slots(business_id, date_selected, duration):
    try:
        p_res = supabase.table("profiles").select("*").eq("id", business_id).single().execute()
        p = p_res.data
        start_t = p.get('work_start', '08:00')
        end_t = p.get('work_end', '18:00')

        existing = supabase.table("appointments") \
            .select("appointment_time, services(duration_minutes)") \
            .eq("business_id", business_id) \
            .gte("appointment_time", f"{date_selected}T00:00") \
            .lte("appointment_time", f"{date_selected}T23:59") \
            .execute().data

        # Monta set de todos os minutos ocupados no dia
        busy_minutes = set()
        for a in existing:
            a_start = datetime.fromisoformat(a['appointment_time'].replace("Z", "+00:00")).replace(tzinfo=None)
            a_duration = a['services']['duration_minutes']
            for i in range(0, a_duration, 30):
                busy_minutes.add((a_start + timedelta(minutes=i)).strftime("%H:%M"))

        slots = []
        current = datetime.combine(date_selected, time.fromisoformat(start_t))
        work_end = datetime.combine(date_selected, time.fromisoformat(end_t))

        while current + timedelta(minutes=duration) <= work_end:
            time_str = current.strftime("%H:%M")
            if time_str not in busy_minutes:
                slots.append(current.time())
            current += timedelta(minutes=30)
        return slots
    except:
        return []

# 4. LOGIN & ACESSO (O CLIENTE DEFINE A SENHA)
def login():
    apply_custom_style()
    st.title("Meridian Pulse")
    st.subheader("Business Performance & Data Intelligence")
    
    tab1, tab2 = st.tabs(["Acessar Painel", "Primeiro Acesso"])
    
    with tab1:
        with st.form("login_form"):
            e = st.text_input("Email").strip()
            p = st.text_input("Senha", type="password")
            if st.form_submit_button("Entrar"):
                try:
                    res = supabase.auth.sign_in_with_password({"email": e, "password": p})
                    st.session_state.user = res.user
                    st.rerun()
                except:
                    st.error("Credenciais inválidas.")
                    
    with tab2:
        st.info("💡 Se você é um novo parceiro Meridian, use seu e-mail cadastrado para definir sua senha de acesso.")
        e_reset = st.text_input("E-mail Cadastrado")
        if st.button("Solicitar Link de Ativação"):
            try:
                supabase.auth.reset_password_for_email(e_reset)
                st.success("Link enviado! Verifique sua caixa de entrada e spam.")
            except Exception as e:
                st.error(f"Erro ao solicitar: {e}")

# 5. DASHBOARD ADMINISTRATIVO (FOCO EM BI)
def dashboard():
    user_id = st.session_state.user.id
    profile = supabase.table("profiles").select("*").eq("id", user_id).single().execute().data
    
    # MELHORIA 1: Passa logo_url para o estilo — se não houver logo cadastrado, nenhuma quebra
    apply_custom_style(
        primary_color=profile['primary_color'],
        secondary_color=profile['secondary_color'],
        logo_url=profile.get('logo_url')
    )
    
    st.sidebar.title(f"MERIDIAN | {profile['business_name']}")
    menu = st.sidebar.radio("Insights & Gestão", ["Performance", "Serviços", "Agenda", "Configurações"])

    if menu == "Performance":
        st.title("Business Intelligence")
        
        # Busca dados para o BI
        appointments = supabase.table("appointments").select("*, services(price, duration_minutes)").eq("business_id", user_id).execute().data
        
        # Cálculos de Receita e Ocupação
        total_receita = sum([a['services']['price'] for a in appointments]) if appointments else 0
        total_clientes = len(appointments) if appointments else 0
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Receita Projetada", f"R$ {total_receita:,.2f}")
        col2.metric("Base de Clientes", total_clientes)
        
        # Ocupação Hoje (Estimada sobre 8h de trabalho)
        hoje = datetime.now().date()
        minutos_hoje = sum([a['services']['duration_minutes'] for a in appointments if a['appointment_time'].startswith(str(hoje))])
        taxa_ocupacao = (minutos_hoje / 480) * 100 if minutos_hoje > 0 else 0
        col3.metric("Ocupação Hoje", f"{taxa_ocupacao:.1f}%")

        st.divider()
        st.subheader("Link de Conversão")
        st.code(f"https://meridian-pulse.streamlit.app/?p={profile['slug']}")
        st.info("💡 Dica Meridian: Sua meta de ocupação para expansão deve ser > 80%.")

    elif menu == "Serviços":
        st.title("Gestão de Portfólio")
        col_f, col_l = st.columns([1, 2])
        with col_f:
            with st.form("svc_add", clear_on_submit=True):
                n = st.text_input("Nome")
                p = st.number_input("Preço (R$)")
                d = st.number_input("Duração (Min)", value=30)
                if st.form_submit_button("Adicionar à Operação"):
                    supabase.table("services").insert({"business_id": user_id, "name": n, "price": p, "duration_minutes": d}).execute()
                    st.rerun()
        with col_l:
            svcs = supabase.table("services").select("*").eq("business_id", user_id).execute().data
            if svcs:
                for s in svcs:
                    st.write(f"**{s['name']}** - R$ {s['price']}")
                    if st.button("Excluir", key=f"d_{s['id']}"):
                        supabase.table("services").delete().eq("id", s['id']).execute()
                        st.rerun()

    elif menu == "Agenda":
        st.title("Fluxo de Atendimento")
        data = supabase.table("appointments").select("created_at, appointment_time, payment_method, clients(full_name, phone), services(name, duration_minutes)").eq("business_id", user_id).order("appointment_time", desc=True).execute().data
        if data:
            rows = []
            for a in data:
                dt_obj = datetime.fromisoformat(a['appointment_time'])
                rows.append({
                    "Cliente": a['clients']['full_name'],
                    "WhatsApp": a['clients']['phone'],
                    "Serviço": a['services']['name'],
                    "Data": dt_obj.strftime('%d/%m/%Y'),
                    "Hora": dt_obj.strftime('%H:%M'),
                    "Pagamento": a.get('payment_method', 'N/A')
                })
            st.table(pd.DataFrame(rows))
        else: st.info("Nenhum agendamento.")

    elif menu == "Configurações":
        st.title("Configurações do Negócio")
        with st.form("config_form"):
            c1, c2 = st.columns(2)
            inicio = c1.text_input("Início (HH:MM)", value=profile.get('work_start', '08:00'))
            fim = c2.text_input("Fim (HH:MM)", value=profile.get('work_end', '18:00'))
            cp = st.color_picker("Cor Primária", value=profile['primary_color'])
            cs = st.color_picker("Cor Secundária", value=profile['secondary_color'])
            # MELHORIA 1: Campo para URL do logo — opcional, não quebra perfis sem logo
            logo = st.text_input("URL do Logo", value=profile.get('logo_url') or "", placeholder="https://...")
            if st.form_submit_button("Atualizar Business Plan"):
                supabase.table("profiles").update({
                    "work_start": inicio,
                    "work_end": fim,
                    "primary_color": cp,
                    "secondary_color": cs,
                    "logo_url": logo if logo else None
                }).eq("id", user_id).execute()
                st.success("Operação atualizada!")
                st.rerun()

# 6. PÁGINA PÚBLICA
def public_booking_page(slug):
    emp = supabase.table("profiles").select("*").eq("slug", slug).single().execute().data
    if not emp: return st.error("Empresa não encontrada.")
    # MELHORIA 1: Passa logo_url para o estilo da página pública
    apply_custom_style(emp['primary_color'], emp['secondary_color'], logo_url=emp.get('logo_url'))

    st.title(emp['business_name'])
    svcs = supabase.table("services").select("*").eq("business_id", emp['id']).execute().data
    if not svcs: return st.warning("Sem serviços disponíveis.")

    s_map = {f"{s['name']} (R$ {s['price']})": s for s in svcs}
    escolha = st.selectbox("O que deseja agendar?", list(s_map.keys()))
    servico = s_map[escolha]

    col1, col2 = st.columns(2)
    data_sel = col1.date_input("Data", min_value=datetime.today())
    slots = get_available_slots(emp['id'], data_sel, servico['duration_minutes'])
    
    if slots:
        hora_sel = col2.selectbox("Horários livres", slots)
        with st.form("final_book", clear_on_submit=True):
            n = st.text_input("Nome Completo")
            z = st.text_input("WhatsApp")
            p = st.selectbox("Forma de Pagamento", ["Cartão", "Dinheiro", "E-transfer"])
            if st.form_submit_button("Confirmar Agendamento"):
                if n and z:
                    c_res = supabase.table("clients").select("id").eq("phone", z).eq("business_id", emp['id']).execute().data
                    c_id = c_res[0]['id'] if c_res else supabase.table("clients").insert({"full_name": n, "phone": z, "business_id": emp['id']}).execute().data[0]['id']
                    supabase.table("appointments").insert({"business_id": emp['id'], "client_id": c_id, "service_id": servico['id'], "appointment_time": f"{data_sel}T{hora_sel}", "payment_method": p}).execute()
                    
                    st.success(f"✅ Confirmado! Te esperamos dia {data_sel.strftime('%d/%m')} às {hora_sel}.")
                    st.balloons()
                    import time
                    time.sleep(3)
                    st.rerun()
    else: st.error("Lotação esgotada para esta data.")

# --- EXECUÇÃO ---
params = st.query_params
if "p" in params: public_booking_page(params["p"])
elif 'user' not in st.session_state: login()
else: dashboard()