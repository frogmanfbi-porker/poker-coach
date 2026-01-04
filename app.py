import streamlit as st
import google.generativeai as genai
from PIL import Image
import os

# --- 1. 設定 & モデル自動選択 ---
st.set_page_config(page_title="Gemini Poker Coach (Tournament)", page_icon="🏆")

# APIキーの読み込み
try:
    api_key = st.secrets["GENAI_API_KEY"]
    genai.configure(api_key=api_key)
except FileNotFoundError:
    st.error("APIキーが見つかりません。Secretsを設定してください。")
    st.stop()

def get_best_model_name():
    """利用可能なモデルから最適なものを自動選択"""
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        # 優先順位: Flash最新 > Flash通常 > Pro最新
        for m in available_models:
            if "flash" in m and "latest" in m: return m
        for m in available_models:
            if "flash" in m and "exp" not in m: return m
        for m in available_models:
            if "pro" in m and "latest" in m: return m
        return "gemini-1.5-flash"
    except:
        return "gemini-1.5-flash"

# --- 2. ツール（計算機）の定義 ---
def calculate_pot_odds(bet_to_call: float, pot_size_before_call: float):
    """ポットオッズと必要勝率を計算"""
    total_pot = pot_size_before_call + bet_to_call
    if total_pot == 0: return "Error: Pot is zero"
    required_equity = (bet_to_call / total_pot) * 100
    odds_ratio = (pot_size_before_call / bet_to_call)
    return {
        "required_equity_percent": round(required_equity, 2),
        "pot_odds_ratio": f"{round(odds_ratio, 1)} : 1"
    }

my_tools = [calculate_pot_odds]
selected_model = get_best_model_name()
model = genai.GenerativeModel(selected_model, tools=my_tools)

# --- 3. UIデザイン ---
st.title("🏆 Gemini Poker Coach")
st.caption(f"Model: {selected_model}")

# モード切替
is_tourney = st.toggle("🏆 トーナメントモードを有効にする (Tournament Mode)", value=False)

with st.form("poker_input_form"):
    
    # A. 基本情報（人数追加）
    st.markdown("### 1. Preflop & Info")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        # テーブル人数（デフォルト6人）
        num_players = st.number_input("Players at Table", min_value=2, max_value=9, value=6)
    with c2:
        hero_pos = st.selectbox("Hero Pos", ["UTG", "MP", "CO", "BTN", "SB", "BB"])
    with c3:
        villain_pos = st.selectbox("Villain Pos", ["UTG", "MP", "CO", "BTN", "SB", "BB"])
    with c4:
        hero_hand = st.text_input("Hero Hand", placeholder="AdKd")

    # B. トーナメント情報（条件付き表示）
    tourney_prompt_part = ""
    if is_tourney:
        st.markdown("### 2. Tournament Status (ICM Context)")
        st.info("バブルファクターやICMを考慮してアドバイスします")
        t1, t2, t3 = st.columns(3)
        with t1:
            # 参加人数 / 残り人数
            total_entrants = st.number_input("参加総数", value=100, step=10)
            players_left = st.number_input("現在の残り人数", value=50, step=1)
        with t2:
            # インマネライン / 現在順位
            itm_places = st.number_input("インマネ(ITM)人数", value=15)
            hero_rank = st.number_input("現在の自分の順位", value=25)
        with t3:
            # チップ状況（BB換算が望ましいが実数でも可）
            avg_stack = st.text_input("平均スタック量", placeholder="例: 30BB or 50,000")
            leader_stack = st.text_input("1位のスタック量", placeholder="例: 80BB or 150,000")

    # C. ボード情報
    st.markdown("### 3. Board")
    b1, b2, b3 = st.columns(3)
    with b1: flop_cards = st.text_input("Flop", placeholder="2h 7s Qd")
    with b2: turn_card = st.text_input("Turn", placeholder="As")
    with b3: river_card = st.text_input("River", placeholder="5c")

    # D. ベット状況
    st.markdown("### 4. Pot & Stacks")
    p1, p2, p3 = st.columns(3)
    with p1:
        # トーナメントの場合、M値計算のためBB数が重要
        stack_depth = st.text_input("Hero's Stack (BB)", placeholder="例: 25.5 BB")
    with p2:
        current_pot = st.number_input("Current Pot (ベット込)", min_value=0.0, step=0.5)
    with p3:
        to_call = st.number_input("To Call (必要額)", min_value=0.0, step=0.5)

    # E. その他・画像
    st.markdown("### 5. Others / Image")
    action_history = st.text_area("履歴・メモ", placeholder="Preflop: Hero raise 2.2bb...", height=80)
    uploaded_file = st.file_uploader("スクショ (任意)", type=["jpg", "png"])
    
    if uploaded_file:
        image_input = Image.open(uploaded_file)
        st.image(image_input, width=300)
    else:
        image_input = None

    submit_btn = st.form_submit_button("解析開始 (Analyze)")

# --- 4. 解析ロジック ---
if submit_btn:
    with st.spinner("AIが戦況とICMプレッシャーを分析中..."):
        chat = model.start_chat(enable_automatic_function_calling=True)

        # トーナメント情報のプロンプト組み立て
        game_context = "【ゲームモード: キャッシュゲーム (Cash Game)】\n- ChipEV (cEV) を最大化する戦略を提示してください。"
        if is_tourney:
            game_context = f"""
            【ゲームモード: トーナメント (Tournament Mode)】
            **重要: ICM (Independent Chip Model) と バブルファクターを強く意識してください。**
            
            [トーナメント状況]
            - 参加総数: {total_entrants}名 / 現在残り: {players_left}名
            - インマネ(ITM): {itm_places}名 (現在バブルまでの距離を考慮せよ)
            - Hero順位: {hero_rank}位
            - 平均スタック: {avg_stack} / チップリスタック: {leader_stack}
            
            ※ 生存戦略(Survival)とチップ獲得(Accumulation)のバランスを評価すること。
            """

        board_info = f"Flop: {flop_cards}, Turn: {turn_card}, River: {river_card}"

        prompt = f"""
        あなたは世界最高峰のポーカーコーチです。以下のハンドを分析してください。
        
        {game_context}

        【ハンド情報】
        - テーブル人数: {num_players} max
        - Hero: {hero_pos} / Hand: {hero_hand}
        - Villain: {villain_pos}
        - Hero's Stack: {stack_depth}
        
        【ボード】
        {board_info}

        【数値情報】
        - Current Pot: {current_pot}
        - To Call: {to_call} (計算ツールを使用してオッズを確認すること)
        
        【アクション履歴】
        {action_history}

        【指示】
        1. 状況分析: トーナメントであれば、現在の「飛び」のリスクとリワードが見合っているかICMの観点で解説してください。
        2. レンジ推定: {num_players}人テーブルであることを考慮し、レンジの広さを調整してください。
        3. 推奨アクション: 理由とともに提示してください。
        """

        content = [prompt, image_input] if image_input else [prompt]

        try:
            response = chat.send_message(content)
            st.markdown("### 📝 コーチからのフィードバック")
            st.markdown(response.text)
        except Exception as e:
            st.error(f"エラー: {e}")
