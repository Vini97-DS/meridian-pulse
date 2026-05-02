import streamlit as st
from supabase import create_client, Client
import pandas as pd
from datetime import datetime, timedelta, time
import uuid

# ─────────────────────────────────────────────
# 1. CONEXÃO COM SUPABASE
# ─────────────────────────────────────────────
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

# ─────────────────────────────────────────────
# 2. UX & UI CUSTOMIZADA (PADRÃO MERIDIAN)
# MELHORIA 1: logo_url opcional — sem logo, sem quebra
# ─────────────────────────────────────────────
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

# ─────────────────────────────────────────────
# 3. LÓGICA DE SLOTS
# MELHORIA 2: Bloqueia período completo do serviço
# MELHORIA 3: Considera agendamentos de outros business_id
#             no mesmo local compartilhado (shared_key)
# ─────────────────────────────────────────────
def get_available_slots(business_id, date_selected, duration, location_id=None):
    try:
        p_res = supabase.table("profiles").select("*").eq("id", business_id).single().execute()
        p = p_res.data
        start_t = p.get('work_start', '08:00')
        end_t   = p.get('work_end',   '18:00')

        business_ids_to_check = [business_id]
        shared_key = None
        loc_res = None

        # MELHORIA 3: Se local compartilhado, busca todos os business_ids com o mesmo shared_key
        if location_id:
            loc_res = supabase.table("locations").select("*").eq("id", location_id).single().execute().data
            if loc_res and loc_res.get('is_shared') and loc_res.get('shared_key'):
                shared_key = loc_res['shared_key']
                shared_locs = supabase.table("locations") \
                    .select("business_id") \
                    .eq("shared_key", shared_key) \
                    .execute().data
                business_ids_to_check = list({l['business_id'] for l in shared_locs})

        busy_minutes = set()
        for bid in business_ids_to_check:
            query = supabase.table("appointments") \
                .select("appointment_time, services(duration_minutes)") \
                .eq("business_id", bid) \
                .gte("appointment_time", f"{date_selected}T00:00") \
                .lte("appointment_time", f"{date_selected}T23:59")

            # Filtra pelo location_id correto para cada business
            if location_id and shared_key:
                peer_loc = supabase.table("locations") \
                    .select("id") \
                    .eq("business_id", bid) \
                    .eq("shared_key", shared_key) \
                    .execute().data
                if peer_loc:
                    query = query.eq("location_id", peer_loc[0]['id'])
            elif location_id:
                query = query.eq("location_id", location_id)

            existing = query.execute().data

            # MELHORIA 2: Bloqueia intervalo completo, não só o início
            for a in existing:
                a_start    = datetime.fromisoformat(a['appointment_time'].replace("Z", "+00:00")).replace(tzinfo=None)
                a_duration = a['services']['duration_minutes']
                for i in range(0, a_duration, 30):
                    busy_minutes.add((a_start + timedelta(minutes=i)).strftime("%H:%M"))

        slots = []
        current  = datetime.combine(date_selected, time.fromisoformat(start_t))
        work_end = datetime.combine(date_selected, time.fromisoformat(end_t))

        while current + timedelta(minutes=duration) <= work_end:
            time_str = current.strftime("%H:%M")
            if time_str not in busy_minutes:
                slots.append(current.time())
            current += timedelta(minutes=30)
        return slots
    except:
        return []

# ─────────────────────────────────────────────
# 4. LOGIN & ACESSO
# ─────────────────────────────────────────────
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
            except Exception as ex:
                st.error(f"Erro ao solicitar: {ex}")

# ─────────────────────────────────────────────
# 5. DASHBOARD ADMINISTRATIVO
# ─────────────────────────────────────────────
def dashboard():
    user_id = st.session_state.user.id
    profile = supabase.table("profiles").select("*").eq("id", user_id).single().execute().data

    apply_custom_style(
        primary_color=profile['primary_color'],
        secondary_color=profile['secondary_color'],
        logo_url=profile.get('logo_url')
    )

    st.sidebar.title(f"MERIDIAN | {profile['business_name']}")
    menu = st.sidebar.radio("Insights & Gestão", ["Performance", "Serviços", "Agenda", "Locais", "Configurações"])

    # ── PERFORMANCE ──────────────────────────
    if menu == "Performance":
        st.title("Business Intelligence")

        appointments = supabase.table("appointments") \
            .select("*, services(price, duration_minutes)") \
            .eq("business_id", user_id).execute().data

        total_receita  = sum([a['services']['price'] for a in appointments]) if appointments else 0
        total_clientes = len(appointments) if appointments else 0

        col1, col2, col3 = st.columns(3)
        col1.metric("Receita Projetada", f"R$ {total_receita:,.2f}")
        col2.metric("Base de Clientes",  total_clientes)

        hoje = datetime.now().date()
        minutos_hoje  = sum([a['services']['duration_minutes'] for a in appointments if a['appointment_time'].startswith(str(hoje))])
        taxa_ocupacao = (minutos_hoje / 480) * 100 if minutos_hoje > 0 else 0
        col3.metric("Ocupação Hoje", f"{taxa_ocupacao:.1f}%")

        st.divider()
        st.subheader("Link de Conversão")
        st.code(f"https://meridian-pulse.streamlit.app/?p={profile['slug']}")
        st.info("💡 Dica Meridian: Sua meta de ocupação para expansão deve ser > 80%.")

    # ── SERVIÇOS ─────────────────────────────
    elif menu == "Serviços":
        st.title("Gestão de Portfólio")
        col_f, col_l = st.columns([1, 2])
        with col_f:
            with st.form("svc_add", clear_on_submit=True):
                n = st.text_input("Nome")
                p = st.number_input("Preço (R$)")
                d = st.number_input("Duração (Min)", value=30)
                if st.form_submit_button("Adicionar à Operação"):
                    supabase.table("services").insert({
                        "business_id": user_id, "name": n, "price": p, "duration_minutes": d
                    }).execute()
                    st.rerun()
        with col_l:
            svcs = supabase.table("services").select("*").eq("business_id", user_id).execute().data
            if svcs:
                for s in svcs:
                    st.write(f"**{s['name']}** - R$ {s['price']}")
                    if st.button("Excluir", key=f"d_{s['id']}"):
                        supabase.table("services").delete().eq("id", s['id']).execute()
                        st.rerun()

    # ── AGENDA ───────────────────────────────
    elif menu == "Agenda":
        st.title("Fluxo de Atendimento")
        data = supabase.table("appointments") \
            .select("created_at, appointment_time, payment_method, location_id, clients(full_name, phone), services(name, duration_minutes)") \
            .eq("business_id", user_id) \
            .order("appointment_time", desc=True).execute().data

        locs    = supabase.table("locations").select("id, name").eq("business_id", user_id).execute().data
        loc_map = {l['id']: l['name'] for l in locs} if locs else {}

        if data:
            rows = []
            for a in data:
                dt_obj   = datetime.fromisoformat(a['appointment_time'])
                loc_name = loc_map.get(a.get('location_id'), "—")
                rows.append({
                    "Cliente":   a['clients']['full_name'],
                    "WhatsApp":  a['clients']['phone'],
                    "Serviço":   a['services']['name'],
                    "Local":     loc_name,
                    "Data":      dt_obj.strftime('%d/%m/%Y'),
                    "Hora":      dt_obj.strftime('%H:%M'),
                    "Pagamento": a.get('payment_method', 'N/A')
                })
            st.table(pd.DataFrame(rows))
        else:
            st.info("Nenhum agendamento.")

    # ── LOCAIS (MELHORIA 3) ──────────────────
    elif menu == "Locais":
        st.title("Gestão de Locais de Atendimento")
        st.info("💡 Locais compartilhados bloqueiam automaticamente a agenda de todas as profissionais vinculadas pelo mesmo código.")

        locs = supabase.table("locations").select("*").eq("business_id", user_id).execute().data
        if locs:
            for loc in locs:
                tag = "🔗 Compartilhado" if loc['is_shared'] else "🔒 Individual"
                with st.expander(f"📍 {loc['name']}  —  {tag}"):
                    st.write(f"**Endereço:** {loc.get('address') or 'Não cadastrado'}")
                    if loc['is_shared']:
                        st.write("**Código de compartilhamento:**")
                        st.code(loc.get('shared_key', '—'), language=None)
                        st.caption("Compartilhe este código com as colegas que atendem no mesmo espaço.")
                    if st.button("Excluir local", key=f"del_loc_{loc['id']}"):
                        supabase.table("locations").delete().eq("id", loc['id']).execute()
                        st.rerun()
        else:
            st.info("Nenhum local cadastrado ainda.")

        st.divider()
        st.subheader("Adicionar Novo Local")
        with st.form("loc_add", clear_on_submit=True):
            loc_name     = st.text_input("Nome do Local", placeholder="Ex: Consultório, Loja de Suplementos...")
            loc_address  = st.text_input("Endereço", placeholder="Ex: Rua das Flores, 123 — Centro")
            is_shared    = st.checkbox("Este espaço é compartilhado com outras profissionais")
            shared_key_input = ""
            if is_shared:
                st.info("Para entrar em um espaço já existente, cole o código abaixo. Para criar um novo, deixe em branco — o código será gerado automaticamente.")
                shared_key_input = st.text_input("Código do espaço (opcional)")

            if st.form_submit_button("Adicionar Local"):
                if loc_name:
                    final_key = None
                    if is_shared:
                        final_key = shared_key_input.strip() if shared_key_input.strip() else uuid.uuid4().hex[:8]
                    supabase.table("locations").insert({
                        "business_id": user_id,
                        "name":        loc_name,
                        "address":     loc_address if loc_address else None,
                        "is_shared":   is_shared,
                        "shared_key":  final_key
                    }).execute()
                    st.success(f"Local '{loc_name}' adicionado com sucesso!")
                    st.rerun()
                else:
                    st.warning("Informe o nome do local.")

    # ── CONFIGURAÇÕES ────────────────────────
    elif menu == "Configurações":
        st.title("Configurações do Negócio")

        # ── Informações do Negócio ──
        st.subheader("Informações do Negócio")
        with st.form("config_negocio"):
            business_name = st.text_input("Nome do Negócio", value=profile.get('business_name') or "")
            bio = st.text_area(
                "Descrição / Bio",
                value=profile.get('bio') or "",
                placeholder="Apresente seu negócio para o cliente na página de agendamento..."
            )
            whatsapp = st.text_input(
                "WhatsApp de Contato",
                value=profile.get('whatsapp') or "",
                placeholder="Ex: 5511999999999"
            )
            if st.form_submit_button("Salvar Informações"):
                supabase.table("profiles").update({
                    "business_name": business_name,
                    "bio":           bio      if bio      else None,
                    "whatsapp":      whatsapp if whatsapp else None
                }).eq("id", user_id).execute()
                st.success("Informações atualizadas!")
                st.rerun()

        st.divider()

        # ── Identidade Visual ──
        st.subheader("Identidade Visual")
        with st.form("config_visual"):
            cp   = st.color_picker("Cor Primária",   value=profile['primary_color'])
            cs   = st.color_picker("Cor Secundária", value=profile['secondary_color'])
            logo = st.text_input("URL do Logo", value=profile.get('logo_url') or "", placeholder="https://...")
            if st.form_submit_button("Salvar Identidade Visual"):
                supabase.table("profiles").update({
                    "primary_color":   cp,
                    "secondary_color": cs,
                    "logo_url":        logo if logo else None
                }).eq("id", user_id).execute()
                st.success("Identidade visual atualizada!")
                st.rerun()

        st.divider()

        # ── Horários de Atendimento ──
        st.subheader("Horários de Atendimento")
        with st.form("config_horarios"):
            c1, c2 = st.columns(2)
            inicio      = c1.text_input("Início (HH:MM)", value=profile.get('work_start', '08:00'))
            fim         = c2.text_input("Fim (HH:MM)",    value=profile.get('work_end',   '18:00'))
            c3, c4      = st.columns(2)
            break_start = c3.text_input("Início do Intervalo (HH:MM)", value=profile.get('break_start') or "", placeholder="Ex: 12:00")
            break_end   = c4.text_input("Fim do Intervalo (HH:MM)",    value=profile.get('break_end')   or "", placeholder="Ex: 13:00")
            if st.form_submit_button("Salvar Horários"):
                supabase.table("profiles").update({
                    "work_start":  inicio,
                    "work_end":    fim,
                    "break_start": break_start if break_start else None,
                    "break_end":   break_end   if break_end   else None
                }).eq("id", user_id).execute()
                st.success("Horários atualizados!")
                st.rerun()

        st.divider()

        # ── Atendimento Online ──
        st.subheader("Atendimento Online")
        with st.form("config_online"):
            online_enabled = st.checkbox(
                "Oferecer atendimento online",
                value=profile.get('online_enabled') or False
            )
            st.caption("Quando ativo, o paciente verá 'Online' como opção de local na página de agendamento.")
            if st.form_submit_button("Salvar"):
                supabase.table("profiles").update({
                    "online_enabled": online_enabled
                }).eq("id", user_id).execute()
                st.success("Configuração salva!")
                st.rerun()

        st.divider()

        # ── Taxa de Sinal ──
        st.subheader("Taxa de Sinal")
        with st.form("config_sinal"):
            deposit_amount = st.number_input(
                "Valor do Sinal (R$)",
                value=float(profile.get('deposit_amount') or 0),
                min_value=0.0,
                step=5.0
            )
            deposit_note = st.text_area(
                "Instruções de Pagamento",
                value=profile.get('deposit_note') or "",
                placeholder="Ex: Pix para (11) 99999-9999 — chave CPF. Envie o comprovante pelo WhatsApp."
            )
            st.caption("Quando o valor for maior que zero, o aviso aparece automaticamente na página de agendamento.")
            if st.form_submit_button("Salvar Taxa de Sinal"):
                supabase.table("profiles").update({
                    "deposit_amount": deposit_amount if deposit_amount > 0 else None,
                    "deposit_note":   deposit_note   if deposit_note   else None
                }).eq("id", user_id).execute()
                st.success("Taxa de sinal atualizada!")
                st.rerun()

# ─────────────────────────────────────────────
# 6. PÁGINA PÚBLICA
# MELHORIA 3: Seleção de local, bloqueio cruzado,
#             online, taxa de sinal, endereço, bio
# ─────────────────────────────────────────────
def public_booking_page(slug):
    emp = supabase.table("profiles").select("*").eq("slug", slug).single().execute().data
    if not emp:
        return st.error("Empresa não encontrada.")

    apply_custom_style(emp['primary_color'], emp['secondary_color'], logo_url=emp.get('logo_url'))

    st.title(emp['business_name'])
    if emp.get('bio'):
        st.markdown(f"*{emp['bio']}*")

    svcs = supabase.table("services").select("*").eq("business_id", emp['id']).eq("is_active", True).execute().data
    if not svcs:
        return st.warning("Sem serviços disponíveis no momento.")

    # ── Serviço ──
    s_map   = {f"{s['name']} (R$ {s['price']})": s for s in svcs}
    escolha = st.selectbox("O que deseja agendar?", list(s_map.keys()))
    servico = s_map[escolha]

    # ── Local ──
    locs_fisicos = supabase.table("locations").select("*").eq("business_id", emp['id']).execute().data or []
    opcoes_local = [{"id": l['id'], "label": l['name'], "address": l.get('address'), "is_shared": l.get('is_shared'), "online": False} for l in locs_fisicos]
    if emp.get('online_enabled'):
        opcoes_local.append({"id": None, "label": "💻 Online", "address": None, "is_shared": False, "online": True})

    local_escolhido = None
    if len(opcoes_local) == 1:
        local_escolhido = opcoes_local[0]
    elif len(opcoes_local) > 1:
        label_map       = {o['label']: o for o in opcoes_local}
        local_label     = st.selectbox("Onde deseja ser atendido(a)?", list(label_map.keys()))
        local_escolhido = label_map[local_label]

    if local_escolhido and local_escolhido.get('address'):
        st.info(f"📍 {local_escolhido['address']}")

    # ── Sinal ──
    if emp.get('deposit_amount') and emp['deposit_amount'] > 0:
        st.warning(f"⚠️ Esta reserva exige sinal de **R$ {emp['deposit_amount']:.2f}**\n\n{emp.get('deposit_note') or ''}")

    # ── Data e Hora ──
    location_id = local_escolhido['id'] if local_escolhido and not local_escolhido.get('online') else None

    col1, col2 = st.columns(2)
    data_sel   = col1.date_input("Data", min_value=datetime.today())
    slots      = get_available_slots(emp['id'], data_sel, servico['duration_minutes'], location_id=location_id)

    if slots:
        hora_sel = col2.selectbox("Horários disponíveis", slots)
        with st.form("final_book", clear_on_submit=True):
            n = st.text_input("Nome Completo")
            z = st.text_input("WhatsApp")
            p = st.selectbox("Forma de Pagamento", ["Cartão", "Dinheiro", "Pix", "E-transfer"])
            if st.form_submit_button("Confirmar Agendamento"):
                if n and z:
                    c_res = supabase.table("clients").select("id") \
                        .eq("phone", z).eq("business_id", emp['id']).execute().data
                    c_id  = c_res[0]['id'] if c_res else \
                        supabase.table("clients").insert({
                            "full_name": n, "phone": z, "business_id": emp['id']
                        }).execute().data[0]['id']

                    local_label_conf = local_escolhido['label'] if local_escolhido else "—"
                    supabase.table("appointments").insert({
                        "business_id":      emp['id'],
                        "client_id":        c_id,
                        "service_id":       servico['id'],
                        "appointment_time": f"{data_sel}T{hora_sel}",
                        "payment_method":   p,
                        "location_id":      location_id
                    }).execute()

                    st.success(f"✅ Confirmado! Te esperamos dia {data_sel.strftime('%d/%m')} às {hora_sel} — {local_label_conf}.")
                    st.balloons()
                    import time as t
                    t.sleep(3)
                    st.rerun()
                else:
                    st.warning("Preencha nome e WhatsApp para confirmar.")
    else:
        st.error("Sem horários disponíveis para esta data. Tente outro dia.")

# ─────────────────────────────────────────────
# EXECUÇÃO
# ─────────────────────────────────────────────
params = st.query_params
if "p" in params:
    public_booking_page(params["p"])
elif 'user' not in st.session_state:
    login()
else:
    dashboard()