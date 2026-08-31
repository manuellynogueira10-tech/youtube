import json
import urllib.parse
import urllib.request
from pathlib import Path

URLS = [
    "https://youtu.be/dfP7MNVRd9A",
    "https://youtu.be/3oJ4IHMqUjE",
    "https://youtu.be/wO_d5Ra7j4Q",
    "https://youtu.be/8iIIiWw0IdU",
    "https://youtu.be/r3u4E7dL2oQ",
]


def video_id(url):
    if "youtu.be/" in url:
        return url.split("youtu.be/", 1)[1].split("?", 1)[0]

    parsed = urllib.parse.urlparse(url)

    if "/shorts/" in parsed.path:
        return parsed.path.split("/shorts/", 1)[1].split("/", 1)[0]

    return urllib.parse.parse_qs(
        parsed.query
    ).get("v", [""])[0]


def youtube_oembed(url):
    endpoint = (
        "https://www.youtube.com/oembed?"
        + urllib.parse.urlencode({
            "url": url,
            "format": "json"
        })
    )

    request = urllib.request.Request(
        endpoint,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=15
    ) as response:
        return json.load(response)


def build_item(url, number):
    vid = video_id(url)

    item = {
        "id": vid,
        "title": f"Vídeo {number}",
        "channel": "Canal do YouTube",
        "category": "Destaques",
        "short": "/shorts/" in url
    }

    try:
        data = youtube_oembed(url)

        item["title"] = (
            data.get("title")
            or item["title"]
        )

        item["channel"] = (
            data.get("author_name")
            or item["channel"]
        )

    except Exception as error:
        print(
            "Não foi possível carregar:",
            url,
            error
        )

    return item


def main():
    videos = [
        build_item(url, index)
        for index, url
        in enumerate(URLS, 1)
    ]

    Path(
        "video_list.json"
    ).write_text(
        json.dumps(
            videos,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print(
        f"{len(videos)} vídeos atualizados."
    )


if __name__ == "__main__":
    main()
