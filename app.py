import streamlit as st
import google.generativeai as genai
import os
from PIL import Image

# --- 1. 設定部分 ---
st.set_page_config(page_title="Gemini Poker Coach (Vision)", page_icon="♠️")

# APIキーの読み込み
try:
    api_key = st.secrets["GENAI_API_KEY"]
    genai.configure(api_key=api_key)
except FileNotFoundError:
    st.error("APIキーが見つかりません。Secretsを設定してください。")
    st.stop()

# --- 2. ツール（計算機）の定義 ---
def calculate_pot_odds(bet_to_call: float, pot_size_before_call: float):
    """
    ポットオッズを計算する関数。
    """
    total_pot = pot_size_before_call + bet_to_call
    if total_pot == 0:
        return "Pot size is zero, cannot calculate."
    
    required_equity = (bet_to_call / total_pot) * 100
    odds_ratio = (pot_size_before_call / bet_to_call)
    
    return {
        "required_equity_percent": round(required_equity, 2),
        "pot_odds_ratio": f"{round(odds_ratio, 1)} : 1"
    }

my_tools = [calculate_pot_odds]

# --- モデルの自動選択ロジック ---
def get_best_model_name():
    """
    現在APIで利用可能なモデル一覧を取得し、
    Flash系(高速) > Pro系(高性能) の優先順位で自動選択して返す関数
    """
    try:
        # 1. サーバーから使えるモデル一覧を取得
        available_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)
        
        # 2. 優先順位に基づいて検索
        # (models/gemini-1.5-flash のような形式で返ってくるため、部分一致で探す)
        
        # 優先度1: Flashの最新版エイリアス (gemini-1.5-flash など)
        for model in available_models:
            if "flash" in model and "latest" in model:
                return model
        
        # 優先度2: Flashの通常版 (gemini-1.5-flash, gemini-2.0-flash など)
        # リストは通常、新しい順や標準的な順で返るため、最初に見つかったFlashを使う
        for model in available_models:
            if "flash" in model and "exp" not in model: # 実験版(exp)は避ける
                return model

        # 優先度3: Proの最新版
        for model in available_models:
            if "pro" in model and "latest" in model:
                return model
        
        # 優先度4: Proの通常版
        for model in available_models:
            if "pro" in model and "exp" not in model:
                return model

        # 見つからない場合のフォールバック（決め打ち）
        return "gemini-1.5-flash"

    except Exception as e:
        # エラー時は安全なデフォルト値を返す
        return "gemini-1.5-flash"

# 自動で選ばれたモデル名を取得
selected_model_name = get_best_model_name()

# Streamlitの画面に、現在使われているモデルを表示（確認用）
st.caption(f"Running on: `{selected_model_name}`")

# モデルの準備
model = genai.GenerativeModel(
    selected_model_name,
    tools=my_tools
)

# --- 3. UI部分 ---
st.title("♠️ Gemini Poker Coach")
st.caption("Vision & Tools Enabled")

st.markdown("""
プレイ画面の**スクリーンショット**をアップロードするか、状況を手入力してください。
AIが画面を解析し、計算機を使ってアドバイスします。
""")

# 画像アップローダー
uploaded_file = st.file_uploader("スクリーンショットをアップロード (任意)", type=["jpg", "png", "jpeg"])

image_input = None
if uploaded_file is not None:
    image_input = Image.open(uploaded_file)
    st.image(image_input, caption="アップロードされた画像", use_container_width=True)
    st.info("画像が読み込まれました。フォームの入力は空欄でも構いませんが、補足情報があれば入力してください。")

# 入力フォーム（画像がない場合のバックアップ、または補足用）
with st.form("hand_input_form"):
    st.markdown("▼ **補足情報 / 手入力** (画像がある場合は空欄でもOK)")
    col1, col2 = st.columns(2)
    with col1:
        hero_pos = st.selectbox("Hero Position", ["Unknown", "UTG", "MP", "CO", "BTN", "SB", "BB"])
        hero_hand = st.text_input("Hero Hand", placeholder="例: AhKd (画像なら空欄可)")
    with col2:
        villain_pos = st.selectbox("Villain Position", ["Unknown", "UTG", "MP", "CO", "BTN", "SB", "BB"])
        stack_depth = st.text_input("Stack / Pot", placeholder="例: 100BB (画像なら空欄可)")

    action_history = st.text_area("質問や補足メモ", "この場面、チェックレイズすべき？")
    
    submitted = st.form_submit_button("解析開始 (Analyze)")

# --- 4. 解析ロジック ---
if submitted:
    with st.spinner("Geminiが視覚情報と状況を解析中..."):
        # チャットセッション開始
        chat = model.start_chat(enable_automatic_function_calling=True)
        
        # プロンプトの基本部分
        base_prompt = f"""
        あなたはGTOポーカーコーチです。提供された情報を元に最適なアクションをアドバイスしてください。

        【ユーザー入力情報（補足）】
        - Hero Position: {hero_pos}
        - Hero Hand: {hero_hand}
        - Villain Position: {villain_pos}
        - Stack/Pot Info: {stack_depth}
        - ユーザーの質問: {action_history}
        """

        # 画像がある場合の追加指示
        if image_input:
            img_prompt = """
            【画像分析指示】
            アップロードされた画像はポーカーのプレイ画面または履歴です。
            1. **OCRと状況認識:** 画像から読み取れる全ての情報（カード、スタックサイズ、ポット額、現在のベット額、ポジション、HUDのスタッツなど）を抽出してください。
            2. ユーザーの手入力情報と画像の情報の間に矛盾がある場合は、**画像の情報を優先**してください。
            3. 画像から「ベット額」や「ポット額」が読み取れる場合は、必ず `calculate_pot_odds` ツールを使って正確なオッズを計算してください。
            """
            # 画像とテキストをリストにして送信
            message_content = [base_prompt + img_prompt, image_input]
        else:
            # テキストのみ送信
            message_content = base_prompt + "\n【指示】状況を分析し、必要であれば計算ツールを使ってアドバイスしてください。"

        try:
            # 解析実行
            response = chat.send_message(message_content)
            
            st.markdown("### 📝 コーチからのフィードバック")
            st.markdown(response.text)
            
            # デバッグ用：ツール使用ログ
            with st.expander("思考プロセスとツール使用ログ"):
                for content in chat.history:
                    part = content.parts[0]
                    if fn := part.function_call:
                        st.write(f"🔧 **ツール実行:** `{fn.name}`")
                        st.json(dict(fn.args))
                    if resp := part.function_response:
                        st.write(f"📩 **ツール結果:** `{resp.name}`")

        except Exception as e:

            st.error(f"エラーが発生しました: {e}")


