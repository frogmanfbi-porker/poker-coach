import streamlit as st
import google.generativeai as genai
from PIL import Image
import os

# --- 1. 設定 & モデル自動選択 ---
st.set_page_config(page_title="Gemini Poker Coach (Pro)", page_icon="♠️")

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
        
        # 優先順位: Flash最新 > Flash通常 > Pro最新 > Pro通常
        for m in available_models:
            if "flash" in m and "latest" in m: return m
        for m in available_models:
            if "flash" in m and "exp" not in m: return m
        for m in available_models:
            if "pro" in m and "latest" in m: return m
        return "gemini-1.5-flash" # フォールバック
    except:
        return "gemini-1.5-flash"

# --- 2. ツール（計算機）の定義 ---
def calculate_pot_odds(bet_to_call: float, pot_size_before_call: float):
    """
    ポットオッズと必要勝率を計算する関数。
    Args:
        bet_to_call: コールするのに必要な額
        pot_size_before_call: コールする前のポット総額（相手のベット込み）
    """
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
st.title("♠️ Gemini Poker Coach")
st.caption(f"Model: {selected_model} | Mode: Vision & Manual Input")

st.markdown("状況を入力してください。画像なしでも詳細に分析します。")

# --- 入力エリア ---
with st.form("poker_input_form"):
    
    # A. 基本情報
    st.markdown("### 1. Preflop & Hand")
    c1, c2, c3 = st.columns(3)
    with c1:
        hero_pos = st.selectbox("Hero Position", ["UTG", "MP", "CO", "BTN", "SB", "BB"])
    with c2:
        villain_pos = st.selectbox("Villain Position", ["UTG", "MP", "CO", "BTN", "SB", "BB"])
    with c3:
        hero_hand = st.text_input("Hero Hand", placeholder="例: AhKd")

    # B. ボード情報（ここを強化）
    st.markdown("### 2. Board (Community Cards)")
    st.caption("カードがない場合は空欄でOK（例: フロップだけ入力）")
    b1, b2, b3 = st.columns(3)
    with b1:
        flop_cards = st.text_input("Flop (3 cards)", placeholder="例: 2h 7s Qd")
    with b2:
        turn_card = st.text_input("Turn (1 card)", placeholder="例: As")
    with b3:
        river_card = st.text_input("River (1 card)", placeholder="例: 5c")

    # C. ベット状況（計算用）
    st.markdown("### 3. Pot & Action Info")
    p1, p2, p3 = st.columns(3)
    with p1:
        stack_depth = st.text_input("Effective Stack", placeholder="100 BB")
    with p2:
        current_pot = st.number_input("Current Pot (相手のベット込)", min_value=0.0, step=0.5, help="現在テーブルに出ているチップの総額")
    with p3:
        to_call = st.number_input("To Call (相手のベット額)", min_value=0.0, step=0.5, help="Heroがコールするのに必要な額。0ならチェックorベットの場面")

    # D. その他・画像
    st.markdown("### 4. Others")
    action_history = st.text_area("アクション履歴・補足メモ", placeholder="例: Preflop: Hero open 2.5bb, Villain 3bet to 9bb, Hero Call...", height=100)
    
    uploaded_file = st.file_uploader("スクリーンショット (任意)", type=["jpg", "png"])
    image_input = None
    if uploaded_file:
        image_input = Image.open(uploaded_file)
        st.image(image_input, width=300)

    submit_btn = st.form_submit_button("解析開始 (Analyze)")

# --- 4. 解析ロジック ---
if submit_btn:
    with st.spinner("戦況を分析中...（オッズ計算・レンジ推定）"):
        chat = model.start_chat(enable_automatic_function_calling=True)

        # ボード情報の整理
        board_info = f"Flop: {flop_cards}"
        if turn_card: board_info += f", Turn: {turn_card}"
        if river_card: board_info += f", River: {river_card}"

        # プロンプト作成
        prompt = f"""
        あなたは世界最高峰のGTOポーカーコーチです。以下のハンドを分析してください。

        【ハンド情報】
        - Hero: {hero_pos} / Hand: {hero_hand}
        - Villain: {villain_pos}
        - Effective Stack: {stack_depth}
        
        【ボード】
        {board_info}

        【数値情報（計算用）】
        - Current Pot Size: {current_pot}
        - Amount to Call: {to_call}
        
        【アクション履歴・メモ】
        {action_history}

        【指示】
        1. **状況整理:** 提供されたボードテクスチャ（ウェット/ドライなど）と、互いのレンジの絡み具合を分析してください。
        2. **計算:** `to_call` が0より大きい場合は、必ず `calculate_pot_odds` ツールを使ってオッズを計算してください。
        3. **推奨アクション:** GTOの観点から推奨アクション（頻度含む）を提示してください。
           - なぜそのアクションなのか？（バリューターゲット、ブラフレンジなど）
        """

        # 画像がある場合の処理分岐
        content = [prompt, image_input] if image_input else [prompt]

        try:
            response = chat.send_message(content)
            st.markdown("### 📝 コーチからのフィードバック")
            st.markdown(response.text)
            
            # ツール使用ログ
            with st.expander("AIの思考プロセス（計算ログ）"):
                for history in chat.history:
                    if history.role == "model":
                        for part in history.parts:
                            if part.function_call:
                                st.write(f"🔧 計算実行: `{part.function_call.name}`")
                                st.json(dict(part.function_call.args))
        except Exception as e:
            st.error(f"エラーが発生しました: {e}")
