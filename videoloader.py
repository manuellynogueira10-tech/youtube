#!/usr/bin/env python3

"""
YouTube 2 - Video Loader V3

Tavily -> encontra vídeos
YouTube oEmbed -> confirma vídeo + título + canal
video_list.json -> alimenta o site

SEGURANÇA:
- TAVILY_API_KEY fica somente no ambiente.
- A chave nunca é salva ou impressa.
- Somente URLs oficiais do YouTube são aceitas.
- IDs são validados.
- Respostas possuem limite de tamanho.
- Se ocorrer erro, o video_list.json antigo é preservado.
- O arquivo novo é gravado de forma atômica.
- Não exige instalação de bibliotecas externas.
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ============================================================
# CONFIGURAÇÃO
# ============================================================

TAVILY_API_KEY = os.environ.get(
    "TAVILY_API_KEY",
    ""
).strip()


TAVILY_ENDPOINT = (
    "https://api.tavily.com/search"
)


OUTPUT_FILE = (
    Path(__file__)
    .resolve()
    .with_name("video_list.json")
)


MAX_VIDEOS = 40

RESULTS_PER_QUERY = 20

REQUEST_TIMEOUT = 45

OEMBED_TIMEOUT = 12

MAX_RESPONSE_BYTES = 2_000_000

MAX_OEMBED_BYTES = 300_000


# Duas chamadas básicas:
# até 20 vídeos normais
# até 20 Shorts

SEARCH_QUERIES = (

    (
        "popular trending viral YouTube videos today "
        "music gaming entertainment technology"
    ),

    (
        "popular viral trending YouTube Shorts today"
    ),

)


YOUTUBE_HOSTS = {

    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",

}


VIDEO_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9_-]{11}$"
)


# ============================================================
# ERRO PERSONALIZADO
# ============================================================

class LoaderError(RuntimeError):
    pass


# ============================================================
# TEXTO SEGURO
# ============================================================

def clean_text(
    value: Any,
    limit: int
) -> str:

    text = " ".join(
        str(value or "").split()
    )

    return text[:limit].strip()


# ============================================================
# LEITURA LIMITADA
# ============================================================

def read_limited(
    response,
    max_bytes: int
) -> bytes:

    data = response.read(
        max_bytes + 1
    )

    if len(data) > max_bytes:

        raise LoaderError(
            "Resposta remota excedeu "
            "o limite permitido."
        )

    return data


# ============================================================
# HTTP JSON
# ============================================================

def http_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    headers: dict | None = None,
    timeout: int = REQUEST_TIMEOUT,
    max_bytes: int = MAX_RESPONSE_BYTES,
):

    body = None

    if payload is not None:

        body = json.dumps(
            payload
        ).encode("utf-8")


    request_headers = {

        "Accept":
            "application/json",

        "User-Agent":
            "YouTube2-VideoLoader/3.0",

    }


    if payload is not None:

        request_headers[
            "Content-Type"
        ] = "application/json"


    if headers:

        request_headers.update(
            headers
        )


    request = urllib.request.Request(

        url,

        data=body,

        headers=request_headers,

        method=method,

    )


    try:

        with urllib.request.urlopen(
            request,
            timeout=timeout
        ) as response:

            raw = read_limited(
                response,
                max_bytes
            )


    except urllib.error.HTTPError as error:

        if error.code == 401:

            raise LoaderError(
                "A Tavily recusou a API Key."
            ) from error


        if error.code == 429:

            raise LoaderError(
                "Limite de requisições "
                "da Tavily atingido."
            ) from error


        if error.code in (
            432,
            433
        ):

            raise LoaderError(
                "Limite de créditos/uso "
                "da Tavily atingido."
            ) from error


        raise LoaderError(
            f"Servidor respondeu HTTP "
            f"{error.code}."
        ) from error


    except (
        urllib.error.URLError,
        socket.timeout,
        TimeoutError
    ) as error:

        raise LoaderError(
            f"Falha de rede: {error}"
        ) from error


    try:

        return json.loads(
            raw.decode("utf-8")
        )


    except (
        UnicodeDecodeError,
        json.JSONDecodeError
    ) as error:

        raise LoaderError(
            "O servidor não retornou "
            "um JSON válido."
        ) from error


# ============================================================
# EXTRAIR ID
# ============================================================

def extract_video_id(
    url: str
):

    try:

        parsed = urllib.parse.urlparse(
            url.strip()
        )

    except ValueError:

        return "", False


    if parsed.scheme != "https":

        return "", False


    host = (
        parsed.hostname
        or ""
    ).lower()


    if host not in YOUTUBE_HOSTS:

        return "", False


    path = parsed.path or ""

    video_id = ""

    is_short = False


    # youtu.be/ID

    if host == "youtu.be":

        video_id = (
            path
            .strip("/")
            .split("/", 1)[0]
        )


    # youtube.com/watch?v=ID

    elif path == "/watch":

        video_id = (

            urllib.parse
            .parse_qs(
                parsed.query
            )
            .get(
                "v",
                [""]
            )[0]

        )


    # youtube.com/shorts/ID

    elif path.startswith(
        "/shorts/"
    ):

        video_id = (

            path
            .split(
                "/shorts/",
                1
            )[1]
            .split(
                "/",
                1
            )[0]

        )

        is_short = True


    # youtube.com/live/ID

    elif path.startswith(
        "/live/"
    ):

        video_id = (

            path
            .split(
                "/live/",
                1
            )[1]
            .split(
                "/",
                1
            )[0]

        )


    # youtube.com/embed/ID

    elif path.startswith(
        "/embed/"
    ):

        video_id = (

            path
            .split(
                "/embed/",
                1
            )[1]
            .split(
                "/",
                1
            )[0]

        )


    video_id = video_id.strip()


    if not VIDEO_ID_PATTERN.fullmatch(
        video_id
    ):

        return "", False


    return video_id, is_short


# ============================================================
# BUSCAR NA TAVILY
# ============================================================

def tavily_search(
    query: str
):

    payload = {

        "query":
            query,

        "search_depth":
            "basic",

        "max_results":
            RESULTS_PER_QUERY,

        "topic":
            "general",

        "include_answer":
            False,

        "include_raw_content":
            False,

        "include_images":
            False,

        "include_favicon":
            False,

        "include_domains": [
            "youtube.com",
            "youtu.be"
        ],

        "auto_parameters":
            False,

        "safe_search":
            True,

    }


    result = http_json(

        TAVILY_ENDPOINT,

        method="POST",

        payload=payload,

        headers={

            "Authorization":
                "Bearer "
                + TAVILY_API_KEY

        }

    )


    if not isinstance(
        result,
        dict
    ):

        raise LoaderError(
            "Resposta inesperada "
            "da Tavily."
        )


    results = result.get(
        "results"
    )


    if not isinstance(
        results,
        list
    ):

        raise LoaderError(
            "Lista de resultados "
            "não encontrada."
        )


    return [

        item

        for item in results

        if isinstance(
            item,
            dict
        )

    ]


# ============================================================
# YOUTUBE OEMBED
# ============================================================

def youtube_oembed(
    video_id: str
):

    video_url = (

        "https://www.youtube.com/"
        "watch?v="
        + video_id

    )


    endpoint = (

        "https://www.youtube.com/"
        "oembed?"

        + urllib.parse.urlencode({

            "url":
                video_url,

            "format":
                "json"

        })

    )


    try:

        result = http_json(

            endpoint,

            timeout=OEMBED_TIMEOUT,

            max_bytes=
                MAX_OEMBED_BYTES

        )


    except LoaderError:

        return None


    if not isinstance(
        result,
        dict
    ):

        return None


    return result


# ============================================================
# MONTAR VÍDEO
# ============================================================

def build_video(
    result: dict
):

    url = clean_text(
        result.get("url"),
        500
    )


    video_id, is_short = (
        extract_video_id(url)
    )


    if not video_id:

        return None


    metadata = youtube_oembed(
        video_id
    )


    # Se o próprio YouTube não confirmar,
    # não adicionamos.

    if not metadata:

        return None


    title = clean_text(

        metadata.get("title")
        or result.get("title")
        or "Vídeo",

        180

    )


    channel = clean_text(

        metadata.get(
            "author_name"
        )
        or "YouTube",

        100

    )


    if not title:

        title = "Vídeo"


    if not channel:

        channel = "YouTube"


    return {

        "id":
            video_id,

        "title":
            title,

        "channel":
            channel,

        "category":
            (
                "Shorts"
                if is_short
                else "Vídeos"
            ),

        "short":
            bool(is_short),

        "thumbnail":
            (
                "https://i.ytimg.com/"
                "vi/"
                + video_id
                + "/hqdefault.jpg"
            ),

        "url":
            (
                "https://www.youtube.com/"
                "watch?v="
                + video_id
            )

    }


# ============================================================
# GRAVAÇÃO ATÔMICA
# ============================================================

def write_json_atomic(
    document: dict
):

    folder = OUTPUT_FILE.parent


    file_descriptor, temp_name = (
        tempfile.mkstemp(

            prefix=
                ".video_list.",

            suffix=
                ".tmp",

            dir=str(folder),

            text=True

        )
    )


    temp_file = Path(
        temp_name
    )


    try:

        with os.fdopen(

            file_descriptor,

            "w",

            encoding="utf-8"

        ) as file:

            json.dump(

                document,

                file,

                ensure_ascii=False,

                indent=2

            )

            file.write("\n")

            file.flush()

            os.fsync(
                file.fileno()
            )


        os.replace(

            temp_file,

            OUTPUT_FILE

        )


    finally:

        try:

            temp_file.unlink(
                missing_ok=True
            )

        except Exception:

            pass


# ============================================================
# PRINCIPAL
# ============================================================

def main():

    if not TAVILY_API_KEY:

        print(

            "ERRO: TAVILY_API_KEY "
            "não está definida.",

            file=sys.stderr

        )

        return 2


    videos = []

    seen = set()


    try:

        for index, query in enumerate(
            SEARCH_QUERIES,
            1
        ):

            print()

            print(
                f"Busca {index}/"
                f"{len(SEARCH_QUERIES)}"
            )


            results = tavily_search(
                query
            )


            print(
                "Tavily retornou "
                f"{len(results)} resultados."
            )


            for result in results:

                if len(videos) >= MAX_VIDEOS:

                    break


                video = build_video(
                    result
                )


                if not video:

                    continue


                video_id = video["id"]


                if video_id in seen:

                    continue


                seen.add(
                    video_id
                )


                videos.append(
                    video
                )


                print(
                    " + "
                    + video["title"][:65]
                )


            if index < len(
                SEARCH_QUERIES
            ):

                time.sleep(
                    0.5
                )


    except LoaderError as error:

        print()

        print(
            "ERRO:",
            error,
            file=sys.stderr
        )

        print(
            "O video_list.json "
            "anterior foi preservado.",
            file=sys.stderr
        )

        return 1


    # Nunca substitui o feed por
    # uma lista vazia.

    if not videos:

        print(

            "ERRO: nenhum vídeo "
            "válido encontrado.",

            file=sys.stderr

        )

        print(

            "O JSON antigo "
            "foi preservado.",

            file=sys.stderr

        )

        return 1


    document = {

        "schema_version":
            1,

        "generated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "source":
            "tavily+youtube-oembed",

        "count":
            len(videos),

        "videos":
            videos

    }


    write_json_atomic(
        document
    )


    print()

    print(
        "========================"
    )

    print(
        "ATUALIZAÇÃO CONCLUÍDA"
    )

    print(
        "========================"
    )

    print(
        len(videos),
        "vídeos salvos."
    )

    print(
        "Arquivo:",
        OUTPUT_FILE.name
    )


    return 0


if __name__ == "__main__":

    raise SystemExit(
        main()
    )
