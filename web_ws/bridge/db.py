"""Read-only diary queries for the ODI web application."""

import html
import json
from pathlib import Path

import pymysql
from pymysql.cursors import DictCursor

import config


def _connect():
    if not config.DB["password"]:
        raise RuntimeError("ODI_DB_PASSWORD environment variable is not set")

    return pymysql.connect(
        host=config.DB["host"],
        port=config.DB["port"],
        user=config.DB["user"],
        password=config.DB["password"],
        database=config.DB["database"],
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True,
        connect_timeout=5,
    )


def diary_parts(value):
    """Read new structured diaries and legacy plain text without rewriting either."""
    text = value or ''
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return text, ''
    if (isinstance(data, dict) and data.get('format') == 'odi.diary.v2'
            and all(isinstance(data.get(k), str) for k in ('opening', 'closing'))):
        return data['opening'], data['closing']
    return text, ''


def _web_text(value):
    """Escape stored text while preserving diary line breaks."""
    return html.escape(value or "").replace("\n", "<br>")


def _photo_url(path):
    if not path:
        return None
    return f"/media/obs/{Path(path).name}"


def _format_datetime(value, pattern):
    return value.strftime(pattern) if value else ""


def list_sessions():
    """Return missions that have a saved diary, newest first."""
    query = """
        SELECT
            m.session_id,
            m.started_at,
            d.diary_text,
            COUNT(o.memory_id) AS observed_count,
            MIN(NULLIF(o.representative_image_path, '')) AS representative_image_path
        FROM missions AS m
        INNER JOIN diaries AS d
            ON d.session_id = m.session_id
        LEFT JOIN observations AS o
            ON o.session_id = m.session_id
        GROUP BY
            m.session_id,
            m.started_at,
            d.diary_text
        ORDER BY m.started_at DESC
    """

    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query)
            records = cursor.fetchall()

    return [
        {
            "id": record["session_id"],
            "date": _format_datetime(record["started_at"], "%m.%d"),
            "line": html.escape(
                next(iter(diary_parts(record["diary_text"])[0].splitlines()), "")
            ),
            "date_full": _format_datetime(record["started_at"], "%Y.%m.%d"),
            "photo_url": _photo_url(record.get("representative_image_path")),
            "observed_count": int(record["observed_count"] or 0),
        }
        for record in records
    ]


def get_session(session_id):
    """Return one mission and its diary in the frontend schema."""
    query = """
        SELECT
            m.session_id,
            m.status,
            m.started_at,
            m.completed_at,
            d.diary_text,
            COUNT(o.memory_id) AS observed_count
        FROM missions AS m
        LEFT JOIN diaries AS d
            ON d.session_id = m.session_id
        LEFT JOIN observations AS o
            ON o.session_id = m.session_id
        WHERE m.session_id = %s
        GROUP BY
            m.session_id,
            m.status,
            m.started_at,
            m.completed_at,
            d.diary_text
    """

    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, (session_id,))
            record = cursor.fetchone()

    if record is None:
        return None

    observations = get_observations(session_id)
    started_at = record["started_at"]
    completed_at = record["completed_at"]
    elapsed_seconds = 0
    if started_at and completed_at:
        elapsed_seconds = max(
            0,
            int((completed_at - started_at).total_seconds()),
        )

    diary_text = record["diary_text"] or ""
    opening, closing = diary_parts(diary_text)
    diary_status = (
        "ready"
        if diary_text
        else "generating"
        if record["status"] == "REFLECTING"
        else "missing"
    )
    entries = [
        {
            "observation_id": observation["id"],
            "text": _web_text(observation.get("diary_summary")),
        }
        for observation in observations
    ]

    return {
        "id": record["session_id"],
        "started_at": _format_datetime(started_at, "%Y-%m-%d %H:%M"),
        "ended_at": _format_datetime(completed_at, "%Y-%m-%d %H:%M"),
        "minutes": max(1, round(elapsed_seconds / 60)) if elapsed_seconds else 0,
        "ended_by": record["status"],
        "found_count": len(observations),
        "observed_count": int(record["observed_count"] or 0),
        "diary_status": diary_status,
        "diary": {
            "opening": _web_text(opening),
            "entries": entries,
            "closing": _web_text(closing),
        },
    }


def get_observations(session_id):
    """Return stored observations in chronological order."""
    query = """
        SELECT
            memory_id,
            detection_id,
            object_name,
            object_primary_color,
            object_secondary_color,
            object_material,
            object_shape,
            object_condition,
            representative_image_path,
            diary_summary,
            completed_at,
            stored_at
        FROM observations
        WHERE session_id = %s
        ORDER BY completed_at ASC, stored_at ASC
    """

    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, (session_id,))
            records = cursor.fetchall()

    observations = []
    for record in records:
        observed_at = record["completed_at"] or record["stored_at"]
        observations.append(
            {
                "id": record["detection_id"] or record["memory_id"],
                "session_id": session_id,
                "at": _format_datetime(observed_at, "%H:%M"),
                "label": {
                    "object_name": record["object_name"] or "?",
                    "object_primary_color": (
                        record["object_primary_color"] or ""
                    ),
                    "object_secondary_color": (
                        record["object_secondary_color"] or ""
                    ),
                    "object_material": record["object_material"] or "",
                    "object_shape": record["object_shape"] or "",
                    "object_condition": record["object_condition"] or "",
                },
                "decision": {"action": "OBSERVE"},
                "photo_url": _photo_url(
                    record["representative_image_path"]
                ),
                "diary_summary": record["diary_summary"] or "",
                "observed": True,
            }
        )

    return observations

