from flask import Flask, request, make_response, jsonify, render_template
import requests, os, json, re
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai

if not firebase_admin._apps:
    cred = credentials.Certificate("firebase_key.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()

app = Flask(__name__, template_folder="templates")

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/init")
def webtoon():
    base_url = "https://www.webtoons.com/zh-hant/originals?updateSchedule=MONDAY&sortOrder=UPDATE&webtoonCompleteType=COMPLETED"
    res = requests.get(base_url)
    res.encoding = "utf-8"
    sp = BeautifulSoup(res.text, "html.parser")
    comics = sp.select("ul.card_lst li")

    for comic in comics:
        title = comic.select_one(".subj").text.strip()
        hyperlink = comic.select_one("a")["href"]
        picture = comic.select_one("img")["src"]
        genre = comic.select_one(".genre").text.strip()

        page = 1
        episode_count = 0
        while True:
            inner_url = f"{hyperlink}&page={page}"
            inner_res = requests.get(inner_url)
            inner_res.encoding = "utf-8"
            inner_soup = BeautifulSoup(inner_res.text, "html.parser")
            items = inner_soup.select("li._episodeItem")
            if not items:
                break
            episode_count += len(items)
            page += 1

        doc = {
            "title": title,
            "hyperlink": hyperlink,
            "picture": picture,
            "genre": genre,
            "episodes": f"共 {episode_count} 話"
        }

        comic_id = hyperlink.split("/")[-1]
        db.collection("漫畫含分類").document(comic_id).set(doc)

    return "✅ 漫畫資料已成功初始化並寫入 Firebase！"

@app.route("/webhook", methods=["POST"])
def webhook():
    req = request.get_json(force=True)
    action = req["queryResult"]["action"]

    if action == "genreChoice":
        genre = req["queryResult"]["parameters"].get("genre")
        result = f"您選擇的漫畫分類是：{genre}，相關漫畫如下：\n"
        docs = db.collection("漫畫含分類").get()
        for doc in docs:
            comic = doc.to_dict()
            if genre in comic["genre"]:
                result += f"標題：{comic['title']}\n連結：{comic['hyperlink']}\n\n"
        return make_response(jsonify({"fulfillmentText": result}))

    elif action == "ComicDetail":
        detail = req["queryResult"]["parameters"].get("comicq")
        keyword = req["queryResult"]["parameters"].get("any")
        info = f"您要查詢漫畫的{detail}，關鍵字是：{keyword}\n\n"
        docs = db.collection("漫畫含分類").get()
        found = False
        for doc in docs:
            comic = doc.to_dict()
            if detail == "名稱" and keyword in comic["title"]:
                found = True
                match = re.search(r"共 (\d+) 話", comic["episodes"])
                episode_count = int(match.group(1)) if match else 0
                access_note = "✅ 可以免費觀看全部話次。" if episode_count >= 8 else "⚠️ 需要追漫券才能觀看。"
                info += f"標題：{comic['title']}\n分類：{comic['genre']}\n話次：{comic['episodes']}\n{access_note}\n連結：{comic['hyperlink']}\n圖片：{comic['picture']}\n"
        if not found:
            info += "很抱歉，無符合此關鍵字的漫畫"
        return make_response(jsonify({"fulfillmentText": info}))

    elif action == "input.unknown":
        question = req["queryResult"]["queryText"]
        api_key = os.getenv("API_KEY")
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(question)
        return make_response(jsonify({"fulfillmentText": response.text}))

    return make_response(jsonify({"fulfillmentText": "無法識別的操作"}))

if __name__ == '__main__':
    app.run(debug=True)
