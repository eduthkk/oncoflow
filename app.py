from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date, datetime, time, timedelta
from io import BytesIO
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

APP_TITLE = "OncoFlow — Agenda de Boxes de Infusão | V5 EVENTOS"
APP_VERSION = "V5 EVENTOS — status operacional, linha do tempo do atendimento e relatório de execução"
DB_PATH = Path(__file__).with_name("oncoflow_agenda.db")

ACTIVE_STATUSES = (
    "Agendado",
    "Confirmado",
    "Paciente alocado no box",
    "Pré-QT em andamento",
    "Pré-QT finalizada — aguardando farmácia",
    "Medicamento recebido da farmácia",
    "Infusão em andamento",
    "Infusão pausada por intercorrência",
    "Infusão retomada",
    "Infusão finalizada",
    "Paciente liberado",
)
CANCEL_STATUSES = ("Cancelado", "No-show")
STATUS_OPTIONS = [
    "Agendado",
    "Confirmado",
    "Paciente alocado no box",
    "Pré-QT em andamento",
    "Pré-QT finalizada — aguardando farmácia",
    "Medicamento recebido da farmácia",
    "Infusão em andamento",
    "Infusão pausada por intercorrência",
    "Infusão retomada",
    "Infusão finalizada",
    "Paciente liberado",
    "Cancelado",
    "No-show",
]

OPERATIONAL_EVENT_OPTIONS = [
    "Paciente alocado no box",
    "Pré-QT iniciada",
    "Pré-QT finalizada — aguardando medicamento da farmácia",
    "Medicamento recebido da farmácia",
    "Infusão iniciada",
    "Infusão pausada por intercorrência",
    "Infusão retomada",
    "Infusão finalizada",
    "Paciente liberado",
    "Intercorrência registrada",
    "Observação operacional",
]

EVENT_TO_STATUS = {
    "Paciente alocado no box": "Paciente alocado no box",
    "Pré-QT iniciada": "Pré-QT em andamento",
    "Pré-QT finalizada — aguardando medicamento da farmácia": "Pré-QT finalizada — aguardando farmácia",
    "Medicamento recebido da farmácia": "Medicamento recebido da farmácia",
    "Infusão iniciada": "Infusão em andamento",
    "Infusão pausada por intercorrência": "Infusão pausada por intercorrência",
    "Infusão retomada": "Infusão retomada",
    "Infusão finalizada": "Infusão finalizada",
    "Paciente liberado": "Paciente liberado",
}

DEFAULT_BOXES = 24
DEFAULT_START_HOUR = 7
DEFAULT_END_HOUR = 19
DEFAULT_SLOT_MINUTES = 30

RECORD_SYSTEM_OPTIONS = ["Tasy", "MV"]
DEFAULT_HEALTH_PLANS = [
    "AMIL",
    "BRADESCO SAÚDE",
    "SULAMÉRICA",
    "PORTO SEGURO",
    "NOTRE DAME INTERMÉDICA",
    "UNIMED",
    "CARE PLUS",
    "OMINT",
    "CASSI",
    "GEAP",
    "PARTICULAR",
    "OUTRO",
]
CYCLE_DAY_OPTIONS = ["D1", "D2", "D3", "D4", "D5", "D8", "D15", "D22", "D28", "Outro"]
CYCLE_NUMBER_OPTIONS = [f"C{i}" for i in range(1, 13)]
INFUSION_DURATION_OPTIONS = [30, 45, 60, 90, 120, 150, 180, 240, 300, 360, 480]


# -----------------------------
# Banco de dados
# -----------------------------

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def add_column_if_missing(conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
    if column_name not in table_columns(conn, table_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def init_db() -> None:
    """Cria/migra o banco local.

    A migração mantém compatibilidade com a primeira versão do app, caso o usuário já tenha criado dados.
    Regras críticas continuam validadas na aplicação para facilitar futura migração para SharePoint/SQL.
    """
    with closing(get_conn()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS health_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS patients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                record_system TEXT,
                medical_record TEXT,
                birthdate TEXT,
                health_plan TEXT,
                phone TEXT,
                notes TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS boxes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                location TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER NOT NULL,
                box_id INTEGER NOT NULL,
                start_datetime TEXT NOT NULL,
                end_datetime TEXT NOT NULL,
                infusion_minutes INTEGER,
                status TEXT NOT NULL DEFAULT 'Agendado',
                protocol TEXT,
                medication TEXT,
                cycle_number TEXT,
                cycle_day TEXT,
                responsible_team TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(patient_id) REFERENCES patients(id),
                FOREIGN KEY(box_id) REFERENCES boxes(id)
            );

            CREATE TABLE IF NOT EXISTS appointment_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                appointment_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                event_datetime TEXT NOT NULL,
                user_name TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(appointment_id) REFERENCES appointments(id) ON DELETE CASCADE
            );
            """
        )

        # Migra bases criadas pela versão anterior.
        add_column_if_missing(conn, "patients", "record_system", "TEXT")
        add_column_if_missing(conn, "patients", "medical_record", "TEXT")
        add_column_if_missing(conn, "appointments", "cycle_number", "TEXT")
        add_column_if_missing(conn, "appointments", "infusion_minutes", "INTEGER")

        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_patients_record ON patients(record_system, medical_record);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_patients_record_unique
                ON patients(record_system, medical_record)
                WHERE active = 1 AND record_system IS NOT NULL AND medical_record IS NOT NULL;

            CREATE INDEX IF NOT EXISTS idx_appointments_start ON appointments(start_datetime);
            CREATE INDEX IF NOT EXISTS idx_appointments_box ON appointments(box_id, start_datetime, end_datetime);
            CREATE INDEX IF NOT EXISTS idx_appointments_patient ON appointments(patient_id, start_datetime, end_datetime);
            CREATE INDEX IF NOT EXISTS idx_appointments_cycle
                ON appointments(patient_id, protocol, cycle_number, cycle_day, status);
            CREATE INDEX IF NOT EXISTS idx_events_appointment ON appointment_events(appointment_id, event_datetime);
            CREATE INDEX IF NOT EXISTS idx_events_type ON appointment_events(event_type, event_datetime);
            """
        )
        conn.commit()


def seed_boxes_if_empty(total: int = DEFAULT_BOXES) -> None:
    with closing(get_conn()) as conn:
        count = conn.execute("SELECT COUNT(*) AS total FROM boxes").fetchone()["total"]
        if count == 0:
            now = now_iso()
            conn.executemany(
                "INSERT INTO boxes (name, location, active, created_at) VALUES (?, ?, 1, ?)",
                [(f"Box {i:02d}", "Infusão", now) for i in range(1, total + 1)],
            )
            conn.commit()


def seed_health_plans_if_empty() -> None:
    with closing(get_conn()) as conn:
        count = conn.execute("SELECT COUNT(*) AS total FROM health_plans").fetchone()["total"]
        if count == 0:
            now = now_iso()
            conn.executemany(
                "INSERT INTO health_plans (name, active, created_at) VALUES (?, 1, ?)",
                [(plan, now) for plan in DEFAULT_HEALTH_PLANS],
            )
            conn.commit()


def read_df(query: str, params: tuple = ()) -> pd.DataFrame:
    with closing(get_conn()) as conn:
        return pd.read_sql_query(query, conn, params=params)


def execute(query: str, params: tuple = ()) -> int:
    with closing(get_conn()) as conn:
        cur = conn.execute(query, params)
        conn.commit()
        return int(cur.lastrowid or 0)


def normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    return " ".join(str(value).strip().split())


def normalize_key(value: str | None) -> str:
    return normalize_text(value).upper()


def normalize_cycle_day(value: str | None) -> str:
    raw = normalize_key(value).replace(" ", "")
    if not raw:
        return ""
    if raw.startswith("D"):
        return raw
    if raw.isdigit():
        return f"D{raw}"
    return raw


def normalize_cycle_number(value: str | None) -> str:
    raw = normalize_key(value).replace(" ", "")
    if not raw:
        return ""
    if raw.startswith("C"):
        return raw
    if raw.isdigit():
        return f"C{raw}"
    return raw


def get_active_health_plans() -> pd.DataFrame:
    return read_df(
        """
        SELECT id, name
        FROM health_plans
        WHERE active = 1
        ORDER BY name COLLATE NOCASE
        """
    )


def create_health_plan(name: str) -> int:
    return execute(
        "INSERT INTO health_plans (name, active, created_at) VALUES (?, 1, ?)",
        (normalize_key(name), now_iso()),
    )


def ensure_health_plan(name: str) -> str:
    """Garante que o convênio exista na tabela de opções e retorna o nome normalizado."""
    plan = normalize_key(name)
    if not plan:
        return ""
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT id FROM health_plans WHERE upper(trim(name)) = upper(trim(?)) LIMIT 1",
            (plan,),
        ).fetchone()
        if row:
            if int(conn.execute("SELECT active FROM health_plans WHERE id = ?", (row["id"],)).fetchone()["active"]) == 0:
                conn.execute("UPDATE health_plans SET active = 1 WHERE id = ?", (row["id"],))
                conn.commit()
            return plan
        conn.execute("INSERT INTO health_plans (name, active, created_at) VALUES (?, 1, ?)", (plan, now_iso()))
        conn.commit()
    return plan


def get_active_patients() -> pd.DataFrame:
    return read_df(
        """
        SELECT id, name, record_system, medical_record, birthdate, health_plan, phone, notes
        FROM patients
        WHERE active = 1
        ORDER BY name COLLATE NOCASE
        """
    )


def find_patient_by_record(record_system: str, medical_record: str) -> Optional[sqlite3.Row]:
    with closing(get_conn()) as conn:
        return conn.execute(
            """
            SELECT id, name, record_system, medical_record, health_plan
            FROM patients
            WHERE active = 1
              AND upper(trim(record_system)) = upper(trim(?))
              AND upper(trim(medical_record)) = upper(trim(?))
            LIMIT 1
            """,
            (record_system, medical_record),
        ).fetchone()


def find_patient_by_record_except(record_system: str, medical_record: str, patient_id: int) -> Optional[sqlite3.Row]:
    with closing(get_conn()) as conn:
        return conn.execute(
            """
            SELECT id, name, record_system, medical_record, health_plan
            FROM patients
            WHERE active = 1
              AND id <> ?
              AND upper(trim(record_system)) = upper(trim(?))
              AND upper(trim(medical_record)) = upper(trim(?))
            LIMIT 1
            """,
            (patient_id, record_system, medical_record),
        ).fetchone()


def get_patient_by_id(patient_id: int) -> Optional[sqlite3.Row]:
    with closing(get_conn()) as conn:
        return conn.execute(
            """
            SELECT id, name, record_system, medical_record, birthdate, health_plan, phone, notes, active
            FROM patients
            WHERE id = ?
            LIMIT 1
            """,
            (patient_id,),
        ).fetchone()


def get_active_boxes() -> pd.DataFrame:
    return read_df(
        """
        SELECT id, name, location
        FROM boxes
        WHERE active = 1
        ORDER BY name COLLATE NOCASE
        """
    )


def get_day_appointments(selected_date: date) -> pd.DataFrame:
    start_day = datetime.combine(selected_date, time.min).isoformat(timespec="seconds")
    end_day = datetime.combine(selected_date + timedelta(days=1), time.min).isoformat(timespec="seconds")
    return read_df(
        """
        SELECT
            a.id,
            p.name AS paciente,
            p.record_system AS sistema_prontuario,
            p.medical_record AS prontuario,
            p.health_plan AS convenio,
            b.name AS box,
            a.start_datetime AS inicio,
            a.end_datetime AS fim,
            a.infusion_minutes AS tempo_infusao_min,
            a.status,
            a.protocol AS protocolo,
            a.medication AS medicamento,
            a.cycle_number AS ciclo,
            a.cycle_day AS ciclo_dia,
            a.responsible_team AS equipe,
            a.notes AS observacoes
        FROM appointments a
        JOIN patients p ON p.id = a.patient_id
        JOIN boxes b ON b.id = a.box_id
        WHERE a.start_datetime < ?
          AND a.end_datetime > ?
        ORDER BY a.start_datetime, b.name, p.name
        """,
        (end_day, start_day),
    )


def get_all_future_appointments(limit: int = 500) -> pd.DataFrame:
    return read_df(
        """
        SELECT
            a.id,
            p.name AS paciente,
            p.record_system AS sistema_prontuario,
            p.medical_record AS prontuario,
            p.health_plan AS convenio,
            b.name AS box,
            a.start_datetime AS inicio,
            a.end_datetime AS fim,
            a.infusion_minutes AS tempo_infusao_min,
            a.status,
            a.protocol AS protocolo,
            a.medication AS medicamento,
            a.cycle_number AS ciclo,
            a.cycle_day AS ciclo_dia
        FROM appointments a
        JOIN patients p ON p.id = a.patient_id
        JOIN boxes b ON b.id = a.box_id
        WHERE a.end_datetime >= ?
        ORDER BY a.start_datetime
        LIMIT ?
        """,
        (now_iso(), limit),
    )


def find_time_conflicts(
    *,
    patient_id: int,
    box_id: int,
    start_dt: datetime,
    end_dt: datetime,
    ignore_appointment_id: Optional[int] = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    params_box: list = [box_id, end_dt.isoformat(timespec="seconds"), start_dt.isoformat(timespec="seconds")]
    params_patient: list = [patient_id, end_dt.isoformat(timespec="seconds"), start_dt.isoformat(timespec="seconds")]
    ignore_clause = ""
    if ignore_appointment_id:
        ignore_clause = " AND a.id <> ?"
        params_box.append(ignore_appointment_id)
        params_patient.append(ignore_appointment_id)

    box_conflicts = read_df(
        f"""
        SELECT
            a.id, p.name AS paciente, p.record_system AS sistema_prontuario, p.medical_record AS prontuario,
            b.name AS box, a.start_datetime AS inicio, a.end_datetime AS fim, a.status,
            a.protocol AS protocolo, a.cycle_number AS ciclo, a.cycle_day AS ciclo_dia
        FROM appointments a
        JOIN patients p ON p.id = a.patient_id
        JOIN boxes b ON b.id = a.box_id
        WHERE a.box_id = ?
          AND a.status NOT IN ('Cancelado', 'No-show')
          AND a.start_datetime < ?
          AND a.end_datetime > ?
          {ignore_clause}
        ORDER BY a.start_datetime
        """,
        tuple(params_box),
    )
    patient_conflicts = read_df(
        f"""
        SELECT
            a.id, p.name AS paciente, p.record_system AS sistema_prontuario, p.medical_record AS prontuario,
            b.name AS box, a.start_datetime AS inicio, a.end_datetime AS fim, a.status,
            a.protocol AS protocolo, a.cycle_number AS ciclo, a.cycle_day AS ciclo_dia
        FROM appointments a
        JOIN patients p ON p.id = a.patient_id
        JOIN boxes b ON b.id = a.box_id
        WHERE a.patient_id = ?
          AND a.status NOT IN ('Cancelado', 'No-show')
          AND a.start_datetime < ?
          AND a.end_datetime > ?
          {ignore_clause}
        ORDER BY a.start_datetime
        """,
        tuple(params_patient),
    )
    return box_conflicts, patient_conflicts


def find_cycle_conflicts(
    *,
    patient_id: int,
    protocol: str,
    cycle_number: str,
    cycle_day: str,
    selected_date: date,
    ignore_appointment_id: Optional[int] = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Valida regras clínicas/operacionais do ciclo.

    Regra 1: mesmo paciente + protocolo + ciclo + D não pode existir mais de uma vez em agenda ativa.
    Regra 2: mesmo paciente + protocolo + ciclo não pode ter dois D diferentes na mesma data.
    """
    protocol_norm = normalize_key(protocol)
    cycle_number_norm = normalize_cycle_number(cycle_number)
    cycle_day_norm = normalize_cycle_day(cycle_day)
    date_start = datetime.combine(selected_date, time.min).isoformat(timespec="seconds")
    date_end = datetime.combine(selected_date + timedelta(days=1), time.min).isoformat(timespec="seconds")

    params_duplicate: list = [patient_id, protocol_norm, cycle_number_norm, cycle_day_norm]
    params_same_date: list = [patient_id, protocol_norm, cycle_number_norm, date_end, date_start, cycle_day_norm]
    ignore_clause = ""
    if ignore_appointment_id:
        ignore_clause = " AND a.id <> ?"
        params_duplicate.append(ignore_appointment_id)
        params_same_date.append(ignore_appointment_id)

    common_select = """
        SELECT
            a.id, p.name AS paciente, p.record_system AS sistema_prontuario, p.medical_record AS prontuario,
            b.name AS box, a.start_datetime AS inicio, a.end_datetime AS fim, a.status,
            a.protocol AS protocolo, a.medication AS medicamento,
            a.cycle_number AS ciclo, a.cycle_day AS ciclo_dia
        FROM appointments a
        JOIN patients p ON p.id = a.patient_id
        JOIN boxes b ON b.id = a.box_id
    """

    duplicate_d = read_df(
        f"""
        {common_select}
        WHERE a.patient_id = ?
          AND a.status NOT IN ('Cancelado', 'No-show')
          AND upper(trim(coalesce(a.protocol, ''))) = ?
          AND upper(trim(coalesce(a.cycle_number, ''))) = ?
          AND upper(trim(coalesce(a.cycle_day, ''))) = ?
          {ignore_clause}
        ORDER BY a.start_datetime
        """,
        tuple(params_duplicate),
    )

    same_date_other_day = read_df(
        f"""
        {common_select}
        WHERE a.patient_id = ?
          AND a.status NOT IN ('Cancelado', 'No-show')
          AND upper(trim(coalesce(a.protocol, ''))) = ?
          AND upper(trim(coalesce(a.cycle_number, ''))) = ?
          AND a.start_datetime < ?
          AND a.end_datetime > ?
          AND upper(trim(coalesce(a.cycle_day, ''))) <> ?
          {ignore_clause}
        ORDER BY a.start_datetime
        """,
        tuple(params_same_date),
    )
    return duplicate_d, same_date_other_day


def create_patient(
    *,
    name: str,
    record_system: str,
    medical_record: str,
    birthdate: Optional[date],
    health_plan: str,
    phone: str,
    notes: str,
) -> int:
    return execute(
        """
        INSERT INTO patients (name, record_system, medical_record, birthdate, health_plan, phone, notes, active, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
        """,
        (
            normalize_text(name),
            normalize_key(record_system),
            normalize_key(medical_record),
            birthdate.isoformat() if birthdate else None,
            normalize_key(health_plan),
            normalize_text(phone) or None,
            normalize_text(notes) or None,
            now_iso(),
        ),
    )


def update_patient(
    *,
    patient_id: int,
    name: str,
    record_system: str,
    medical_record: str,
    birthdate: Optional[date],
    health_plan: str,
    phone: str,
    notes: str,
) -> None:
    execute(
        """
        UPDATE patients
        SET name = ?, record_system = ?, medical_record = ?, birthdate = ?, health_plan = ?, phone = ?, notes = ?
        WHERE id = ?
        """,
        (
            normalize_text(name),
            normalize_key(record_system),
            normalize_key(medical_record),
            birthdate.isoformat() if birthdate else None,
            normalize_key(health_plan),
            normalize_text(phone) or None,
            normalize_text(notes) or None,
            patient_id,
        ),
    )


def deactivate_patient(patient_id: int) -> None:
    execute("UPDATE patients SET active = 0 WHERE id = ?", (patient_id,))


def create_box(name: str, location: str) -> int:
    return execute(
        "INSERT INTO boxes (name, location, active, created_at) VALUES (?, ?, 1, ?)",
        (normalize_text(name), normalize_text(location) or None, now_iso()),
    )


def create_appointment(
    *,
    patient_id: int,
    box_id: int,
    start_dt: datetime,
    end_dt: datetime,
    infusion_minutes: int,
    status: str,
    protocol: str,
    medication: str,
    cycle_number: str,
    cycle_day: str,
    responsible_team: str,
    notes: str,
) -> int:
    appointment_id = execute(
        """
        INSERT INTO appointments (
            patient_id, box_id, start_datetime, end_datetime, infusion_minutes, status,
            protocol, medication, cycle_number, cycle_day, responsible_team, notes, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            box_id,
            start_dt.isoformat(timespec="seconds"),
            end_dt.isoformat(timespec="seconds"),
            int(infusion_minutes),
            status,
            normalize_key(protocol),
            normalize_text(medication) or None,
            normalize_cycle_number(cycle_number),
            normalize_cycle_day(cycle_day),
            normalize_text(responsible_team) or None,
            normalize_text(notes) or None,
            now_iso(),
            now_iso(),
        ),
    )
    log_appointment_event(
        appointment_id=appointment_id,
        event_type="Agendamento criado",
        event_datetime=now_iso(),
        user_name="Sistema",
        notes=f"Status inicial: {status}",
        update_status=False,
    )
    if status not in ("Agendado", ""):
        log_appointment_event(
            appointment_id=appointment_id,
            event_type=status,
            event_datetime=now_iso(),
            user_name="Sistema",
            notes="Status inicial registrado no agendamento.",
            update_status=False,
        )
    return appointment_id

def get_appointment_by_id(appointment_id: int) -> Optional[sqlite3.Row]:
    with closing(get_conn()) as conn:
        return conn.execute(
            """
            SELECT
                a.id, a.patient_id, a.box_id, a.start_datetime, a.end_datetime, a.infusion_minutes,
                a.status, a.protocol, a.medication, a.cycle_number, a.cycle_day,
                a.responsible_team, a.notes,
                p.name AS paciente, b.name AS box
            FROM appointments a
            JOIN patients p ON p.id = a.patient_id
            JOIN boxes b ON b.id = a.box_id
            WHERE a.id = ?
            LIMIT 1
            """,
            (appointment_id,),
        ).fetchone()


def update_appointment(
    *,
    appointment_id: int,
    patient_id: int,
    box_id: int,
    start_dt: datetime,
    end_dt: datetime,
    infusion_minutes: int,
    status: str,
    protocol: str,
    medication: str,
    cycle_number: str,
    cycle_day: str,
    responsible_team: str,
    notes: str,
) -> None:
    execute(
        """
        UPDATE appointments
        SET patient_id = ?, box_id = ?, start_datetime = ?, end_datetime = ?, infusion_minutes = ?,
            status = ?, protocol = ?, medication = ?, cycle_number = ?, cycle_day = ?,
            responsible_team = ?, notes = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            patient_id,
            box_id,
            start_dt.isoformat(timespec="seconds"),
            end_dt.isoformat(timespec="seconds"),
            int(infusion_minutes),
            status,
            normalize_key(protocol),
            normalize_text(medication) or None,
            normalize_cycle_number(cycle_number),
            normalize_cycle_day(cycle_day),
            normalize_text(responsible_team) or None,
            normalize_text(notes) or None,
            now_iso(),
            appointment_id,
        ),
    )


def validate_appointment_rules(
    *,
    patient_id: int,
    box_id: int,
    start_dt: datetime,
    end_dt: datetime,
    infusion_minutes: int,
    protocol: str,
    cycle_number: str,
    cycle_day: str,
    ignore_appointment_id: Optional[int] = None,
) -> tuple[list[str], dict[str, pd.DataFrame]]:
    errors: list[str] = []
    protocol_norm = normalize_key(protocol)
    cycle_number_norm = normalize_cycle_number(cycle_number)
    cycle_day_norm = normalize_cycle_day(cycle_day)

    if not protocol_norm:
        errors.append("Informe o Protocolo/Pedido.")
    if not cycle_number_norm:
        errors.append("Informe o ciclo.")
    if not cycle_day_norm:
        errors.append("Informe o D do ciclo.")
    if infusion_minutes <= 0:
        errors.append("Informe um tempo de infusão maior que zero.")
    if end_dt <= start_dt:
        errors.append("A data/hora final precisa ser maior que a inicial.")

    conflicts: dict[str, pd.DataFrame] = {}
    if errors:
        return errors, conflicts

    box_conflicts, patient_conflicts = find_time_conflicts(
        patient_id=patient_id,
        box_id=box_id,
        start_dt=start_dt,
        end_dt=end_dt,
        ignore_appointment_id=ignore_appointment_id,
    )
    duplicate_d, same_date_other_day = find_cycle_conflicts(
        patient_id=patient_id,
        protocol=protocol_norm,
        cycle_number=cycle_number_norm,
        cycle_day=cycle_day_norm,
        selected_date=start_dt.date(),
        ignore_appointment_id=ignore_appointment_id,
    )
    conflicts = {
        "Conflito no box": box_conflicts,
        "Conflito de horário para o mesmo paciente": patient_conflicts,
        "Duplicidade do mesmo D do ciclo": duplicate_d,
        "Outro D já agendado na mesma data para o mesmo protocolo/ciclo": same_date_other_day,
    }
    return errors, conflicts


def show_appointment_validation_result(errors: list[str], conflicts: dict[str, pd.DataFrame]) -> bool:
    if errors:
        for error in errors:
            st.error(error)
        return False
    active_conflicts = {title: df for title, df in conflicts.items() if not df.empty}
    if active_conflicts:
        st.error("Conflito encontrado. A alteração não foi salva.")
        for title, df in active_conflicts.items():
            st.markdown(f"**{title}:**")
            st.dataframe(format_appointment_table(df), use_container_width=True, hide_index=True)
        return False
    return True


def log_appointment_event(
    *,
    appointment_id: int,
    event_type: str,
    event_datetime: str | datetime | None = None,
    user_name: str = "",
    notes: str = "",
    update_status: bool = True,
) -> int:
    if isinstance(event_datetime, datetime):
        event_dt_iso = event_datetime.isoformat(timespec="seconds")
    elif event_datetime:
        event_dt_iso = str(event_datetime)
    else:
        event_dt_iso = now_iso()

    event = normalize_text(event_type)
    event_id = execute(
        """
        INSERT INTO appointment_events (appointment_id, event_type, event_datetime, user_name, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            appointment_id,
            event,
            event_dt_iso,
            normalize_text(user_name) or None,
            normalize_text(notes) or None,
            now_iso(),
        ),
    )
    if update_status and event in EVENT_TO_STATUS:
        execute(
            "UPDATE appointments SET status = ?, updated_at = ? WHERE id = ?",
            (EVENT_TO_STATUS[event], now_iso(), appointment_id),
        )
    return event_id


def update_appointment_status(appointment_id: int, status: str, *, user_name: str = "", notes: str = "") -> None:
    execute(
        "UPDATE appointments SET status = ?, updated_at = ? WHERE id = ?",
        (status, now_iso(), appointment_id),
    )
    log_appointment_event(
        appointment_id=appointment_id,
        event_type=status,
        event_datetime=now_iso(),
        user_name=user_name or "Atualização rápida",
        notes=notes or "Status alterado direto na agenda do dia.",
        update_status=False,
    )


def get_appointment_events(appointment_id: int | None = None, start_date: Optional[date] = None, end_date: Optional[date] = None) -> pd.DataFrame:
    params: list = []
    filters: list[str] = []
    if appointment_id is not None:
        filters.append("e.appointment_id = ?")
        params.append(appointment_id)
    if start_date is not None:
        filters.append("e.event_datetime >= ?")
        params.append(datetime.combine(start_date, time.min).isoformat(timespec="seconds"))
    if end_date is not None:
        filters.append("e.event_datetime < ?")
        params.append(datetime.combine(end_date + timedelta(days=1), time.min).isoformat(timespec="seconds"))
    where = "WHERE " + " AND ".join(filters) if filters else ""
    return read_df(
        f"""
        SELECT
            e.id,
            e.appointment_id,
            p.name AS paciente,
            p.record_system AS sistema_prontuario,
            p.medical_record AS prontuario,
            p.health_plan AS convenio,
            b.name AS box,
            a.start_datetime AS inicio_previsto,
            a.end_datetime AS fim_previsto,
            a.status AS status_atual,
            a.protocol AS protocolo,
            a.cycle_number AS ciclo,
            a.cycle_day AS ciclo_dia,
            e.event_type AS evento,
            e.event_datetime AS quando,
            e.user_name AS usuario,
            e.notes AS observacoes,
            e.created_at AS registrado_em
        FROM appointment_events e
        JOIN appointments a ON a.id = e.appointment_id
        JOIN patients p ON p.id = a.patient_id
        JOIN boxes b ON b.id = a.box_id
        {where}
        ORDER BY e.event_datetime DESC, e.id DESC
        """,
        tuple(params),
    )


def delete_appointment(appointment_id: int) -> None:
    execute("DELETE FROM appointment_events WHERE appointment_id = ?", (appointment_id,))
    execute("DELETE FROM appointments WHERE id = ?", (appointment_id,))


# -----------------------------
# Cálculos de agenda/ocupação
# -----------------------------

def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def human_duration_minutes(minutes: int) -> str:
    hours = minutes // 60
    mins = minutes % 60
    if hours and mins:
        return f"{hours}h{mins:02d}"
    if hours:
        return f"{hours}h"
    return f"{mins}min"


def calculate_kpis(day_df: pd.DataFrame, selected_date: date, open_time: time, close_time: time, active_boxes_count: int) -> dict:
    if day_df.empty:
        scheduled_minutes = 0
        unique_patients = 0
        active_appointments = 0
    else:
        working_df = day_df[~day_df["status"].isin(CANCEL_STATUSES)].copy()
        active_appointments = len(working_df)
        unique_patients = working_df["paciente"].nunique()
        scheduled_minutes = 0
        for _, row in working_df.iterrows():
            start = max(parse_iso(row["inicio"]), datetime.combine(selected_date, open_time))
            end = min(parse_iso(row["fim"]), datetime.combine(selected_date, close_time))
            scheduled_minutes += max(0, int((end - start).total_seconds() // 60))

    available_minutes = max(0, int((datetime.combine(selected_date, close_time) - datetime.combine(selected_date, open_time)).total_seconds() // 60))
    total_capacity_minutes = active_boxes_count * available_minutes
    occupancy = scheduled_minutes / total_capacity_minutes if total_capacity_minutes else 0
    return {
        "active_appointments": active_appointments,
        "unique_patients": unique_patients,
        "scheduled_minutes": scheduled_minutes,
        "capacity_minutes": total_capacity_minutes,
        "occupancy": occupancy,
    }


def build_schedule_grid(day_df: pd.DataFrame, selected_date: date, boxes_df: pd.DataFrame, open_time: time, close_time: time, slot_minutes: int) -> pd.DataFrame:
    slots: list[datetime] = []
    cursor = datetime.combine(selected_date, open_time)
    end_limit = datetime.combine(selected_date, close_time)
    while cursor < end_limit:
        slots.append(cursor)
        cursor += timedelta(minutes=slot_minutes)

    grid = pd.DataFrame({"Horário": [s.strftime("%H:%M") for s in slots]})
    for _, box in boxes_df.iterrows():
        grid[box["name"]] = ""

    if day_df.empty:
        return grid

    active_df = day_df[~day_df["status"].isin(CANCEL_STATUSES)].copy()
    for idx, slot_start in enumerate(slots):
        slot_end = slot_start + timedelta(minutes=slot_minutes)
        for _, appt in active_df.iterrows():
            appt_start = parse_iso(appt["inicio"])
            appt_end = parse_iso(appt["fim"])
            if appt_start < slot_end and appt_end > slot_start:
                box_name = appt["box"]
                short_patient = str(appt["paciente"]).split()[0]
                ciclo = f"{appt.get('ciclo') or ''} {appt.get('ciclo_dia') or ''}".strip()
                if appt["status"] in ("Agendado", "Confirmado"):
                    marker = "🟣"
                elif "pausada" in str(appt["status"]).lower() or "intercorrência" in str(appt["status"]).lower():
                    marker = "🔴"
                elif "aguardando" in str(appt["status"]).lower():
                    marker = "🟡"
                else:
                    marker = "🟢"
                text = f"{marker} {short_patient} | {ciclo} | {appt['status']}"
                current = grid.at[idx, box_name]
                grid.at[idx, box_name] = text if not current else f"{current}\n{text}"
    return grid


def format_appointment_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    output = df.copy()
    for col in ["inicio", "fim"]:
        if col in output.columns:
            output[col] = pd.to_datetime(output[col]).dt.strftime("%d/%m/%Y %H:%M")
    rename_map = {
        "id": "ID",
        "paciente": "Paciente",
        "sistema_prontuario": "Sistema",
        "prontuario": "Prontuário",
        "convenio": "Convênio",
        "box": "Box",
        "inicio": "Início",
        "fim": "Fim",
        "tempo_infusao_min": "Tempo infusão (min)",
        "status": "Status",
        "protocolo": "Protocolo/Pedido",
        "medicamento": "Medicamento",
        "ciclo": "Ciclo",
        "ciclo_dia": "D do ciclo",
        "equipe": "Equipe",
        "observacoes": "Observações",
    }
    return output.rename(columns={k: v for k, v in rename_map.items() if k in output.columns})


def df_to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Agenda") -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    return buffer.getvalue()


# -----------------------------
# UI
# -----------------------------

def apply_css() -> None:
    st.markdown(
        """
        <style>
        :root {
          --ra-purple: #76007A;
          --ra-green: #C0ED9B;
          --ra-gray: #969696;
        }
        .main .block-container { padding-top: 1.6rem; }
        div[data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid #eee;
            border-left: 6px solid var(--ra-purple);
            padding: 14px 16px;
            border-radius: 14px;
            box-shadow: 0 1px 8px rgba(0,0,0,.05);
        }
        .ra-card {
            background: linear-gradient(135deg, #76007A 0%, #4d0050 100%);
            color: white;
            border-radius: 18px;
            padding: 22px 26px;
            margin-bottom: 18px;
        }
        .ra-card h1 { margin: 0; font-size: 1.8rem; }
        .ra-card p { margin: 8px 0 0 0; color: #f3e6f4; }
        .hint {
            background: #f7f7f7;
            border-left: 5px solid #C0ED9B;
            padding: 12px 14px;
            border-radius: 10px;
            color: #333;
        }
        .danger-hint {
            background: #fff5f7;
            border-left: 5px solid #c62828;
            padding: 12px 14px;
            border-radius: 10px;
            color: #333;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header() -> None:
    st.markdown(
        f"""
        <div class="ra-card">
            <h1>{APP_TITLE}</h1>
            <p><b>VERSÃO V5 EVENTOS</b> — status operacional, linha do tempo do atendimento e relatório de execução.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar() -> tuple[date, time, time, int]:
    st.sidebar.title("⚙️ Parâmetros")
    st.sidebar.success(APP_VERSION)
    selected_date = st.sidebar.date_input("Data da agenda", value=date.today(), format="DD/MM/YYYY")
    open_time = st.sidebar.time_input("Abertura", value=time(DEFAULT_START_HOUR, 0), step=timedelta(minutes=30))
    close_time = st.sidebar.time_input("Fechamento", value=time(DEFAULT_END_HOUR, 0), step=timedelta(minutes=30))
    slot_minutes = st.sidebar.selectbox("Grade de horário", [15, 30, 45, 60], index=1)

    st.sidebar.divider()
    st.sidebar.caption("Conflito considera: box ocupado, paciente ocupado, mesmo D duplicado e mais de um D no mesmo dia para o mesmo protocolo/ciclo. Eventos operacionais geram linha do tempo do atendimento.")
    return selected_date, open_time, close_time, slot_minutes


def render_dashboard(selected_date: date, open_time: time, close_time: time, slot_minutes: int) -> None:
    boxes_df = get_active_boxes()
    day_df = get_day_appointments(selected_date)
    kpis = calculate_kpis(day_df, selected_date, open_time, close_time, len(boxes_df))

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Agendamentos ativos", kpis["active_appointments"])
    col2.metric("Pacientes únicos", kpis["unique_patients"])
    col3.metric("Horas agendadas", human_duration_minutes(kpis["scheduled_minutes"]))
    col4.metric("Ocupação do dia", f"{kpis['occupancy']:.1%}")

    st.markdown("### 🗓️ Grade do dia")
    grid = build_schedule_grid(day_df, selected_date, boxes_df, open_time, close_time, slot_minutes)
    st.dataframe(grid, use_container_width=True, hide_index=True)

    with st.expander("⚡ Alterar status direto na agenda do dia", expanded=True):
        if day_df.empty:
            st.info("Nenhum agendamento nesta data para atualizar status.")
        else:
            quick_df = day_df[["id", "paciente", "box", "inicio", "fim", "status", "protocolo", "ciclo", "ciclo_dia"]].copy()
            quick_df["inicio"] = pd.to_datetime(quick_df["inicio"]).dt.strftime("%H:%M")
            quick_df["fim"] = pd.to_datetime(quick_df["fim"]).dt.strftime("%H:%M")
            quick_df = quick_df.rename(
                columns={
                    "id": "ID",
                    "paciente": "Paciente",
                    "box": "Box",
                    "inicio": "Início",
                    "fim": "Fim",
                    "status": "Status",
                    "protocolo": "Protocolo",
                    "ciclo": "Ciclo",
                    "ciclo_dia": "D",
                }
            )
            edited = st.data_editor(
                quick_df,
                use_container_width=True,
                hide_index=True,
                disabled=["ID", "Paciente", "Box", "Início", "Fim", "Protocolo", "Ciclo", "D"],
                column_config={"Status": st.column_config.SelectboxColumn("Status", options=STATUS_OPTIONS, required=True)},
                key=f"quick_status_{selected_date.isoformat()}",
            )
            if st.button("Salvar status alterados", type="primary", use_container_width=True):
                original = quick_df.set_index("ID")["Status"].to_dict()
                changed = 0
                for _, row in edited.iterrows():
                    appt_id = int(row["ID"])
                    new_status = str(row["Status"])
                    if original.get(appt_id) != new_status:
                        update_appointment_status(appt_id, new_status, user_name="Agenda do dia")
                        changed += 1
                if changed:
                    st.success(f"{changed} status atualizado(s).")
                    st.rerun()
                else:
                    st.info("Nenhum status foi alterado.")

    with st.expander("🧾 Registrar evento operacional do atendimento", expanded=True):
        if day_df.empty:
            st.info("Nenhum agendamento nesta data para registrar evento.")
        else:
            event_options = {
                f"#{int(row['id'])} | {row['paciente']} | {row['box']} | {pd.to_datetime(row['inicio']).strftime('%H:%M')} | {row['status']}": int(row["id"])
                for _, row in day_df.iterrows()
            }
            col_ev1, col_ev2, col_ev3 = st.columns([2, 1, 1])
            with col_ev1:
                event_appt_label = st.selectbox("Agendamento", list(event_options.keys()), key=f"event_appt_{selected_date.isoformat()}")
                event_type = st.selectbox("Evento", OPERATIONAL_EVENT_OPTIONS, key=f"event_type_{selected_date.isoformat()}")
            with col_ev2:
                event_date = st.date_input("Data do evento", value=selected_date, format="DD/MM/YYYY", key=f"event_date_{selected_date.isoformat()}")
                event_time = st.time_input("Hora do evento", value=datetime.now().time().replace(second=0, microsecond=0), step=timedelta(minutes=1), key=f"event_time_{selected_date.isoformat()}")
            with col_ev3:
                event_user = st.text_input("Responsável/usuário", placeholder="Ex.: Enfermagem", key=f"event_user_{selected_date.isoformat()}")
                update_status_flag = st.checkbox("Atualizar status do agendamento", value=True, key=f"event_update_status_{selected_date.isoformat()}")
            event_notes = st.text_area("Observação do evento", placeholder="Ex.: pausa por reação, aguardando farmácia, paciente sem queixa...", key=f"event_notes_{selected_date.isoformat()}")
            if st.button("Registrar evento operacional", type="primary", use_container_width=True, key=f"save_event_{selected_date.isoformat()}"):
                appt_id = event_options[event_appt_label]
                event_dt = datetime.combine(event_date, event_time)
                log_appointment_event(
                    appointment_id=appt_id,
                    event_type=event_type,
                    event_datetime=event_dt,
                    user_name=event_user,
                    notes=event_notes,
                    update_status=update_status_flag,
                )
                st.success("Evento registrado na linha do tempo do atendimento.")
                st.rerun()

    with st.expander("📋 Lista detalhada dos agendamentos do dia", expanded=True):
        formatted = format_appointment_table(day_df)
        if formatted.empty:
            st.info("Nenhum agendamento nesta data.")
        else:
            st.dataframe(formatted, use_container_width=True, hide_index=True)
            st.download_button(
                "⬇️ Baixar agenda do dia em Excel",
                data=df_to_excel_bytes(formatted, "Agenda do dia"),
                file_name=f"agenda_boxes_{selected_date.isoformat()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )


def render_new_appointment() -> None:
    st.markdown("### ➕ Novo agendamento")
    st.markdown(
        """
        <div class="hint">
        Regras ativas: <b>não permite conflito de box</b>, <b>não permite o mesmo paciente em dois horários sobrepostos</b>,
        <b>não permite repetir o mesmo D do ciclo</b> e <b>não permite D diferentes na mesma data para o mesmo protocolo/ciclo</b>.
        </div>
        """,
        unsafe_allow_html=True,
    )
    patients_df = get_active_patients()
    boxes_df = get_active_boxes()

    if patients_df.empty:
        st.warning("Cadastre pelo menos um paciente antes de agendar.")
        return
    if boxes_df.empty:
        st.warning("Cadastre pelo menos um box antes de agendar.")
        return

    patient_options = {
        f"{row['name']} | {row['record_system'] or 'SIST?'} {row['medical_record'] or 'SEM PRONT.'} | {row['health_plan'] or 'Sem convênio'} | ID {row['id']}": int(row["id"])
        for _, row in patients_df.iterrows()
    }
    box_options = {f"{row['name']} | {row['location'] or 'Sem local'}": int(row["id"]) for _, row in boxes_df.iterrows()}

    with st.form("new_appointment_form", clear_on_submit=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            patient_label = st.selectbox("Paciente *", list(patient_options.keys()))
            box_label = st.selectbox("Box *", list(box_options.keys()))
            selected_date = st.date_input("Data *", value=date.today(), format="DD/MM/YYYY")
            start_time = st.time_input("Horário de início *", value=time(8, 0), step=timedelta(minutes=15))
        with col2:
            selected_duration = st.selectbox("Tempo de infusão previsto *", INFUSION_DURATION_OPTIONS, index=4, format_func=human_duration_minutes)
            custom_duration = st.number_input("Ou informe outro tempo em minutos", min_value=0, max_value=720, value=0, step=15)
            status = st.selectbox("Status", STATUS_OPTIONS, index=0)
            responsible_team = st.text_input("Equipe responsável", placeholder="Ex.: Navegação, Farmácia, Autorização")
        with col3:
            protocol = st.text_input("Protocolo/Pedido *", placeholder="Ex.: PED-12345 ou protocolo terapêutico")
            medication = st.text_input("Medicamento / esquema")
            cycle_number = st.selectbox("Ciclo *", CYCLE_NUMBER_OPTIONS, index=0)
            cycle_day_choice = st.selectbox("D do ciclo *", CYCLE_DAY_OPTIONS, index=0)
            cycle_day_custom = st.text_input("Se Outro, informe o D", placeholder="Ex.: D10", disabled=cycle_day_choice != "Outro")
        notes = st.text_area("Observações")
        submitted = st.form_submit_button("Salvar agendamento")

    if submitted:
        patient_id = patient_options[patient_label]
        box_id = box_options[box_label]
        infusion_minutes = int(custom_duration or selected_duration)
        cycle_day = cycle_day_custom if cycle_day_choice == "Outro" else cycle_day_choice
        cycle_day = normalize_cycle_day(cycle_day)
        cycle_number = normalize_cycle_number(cycle_number)
        protocol = normalize_key(protocol)
        start_dt = datetime.combine(selected_date, start_time)
        end_dt = start_dt + timedelta(minutes=infusion_minutes)

        errors = []
        if not protocol:
            errors.append("Informe o Protocolo/Pedido.")
        if not cycle_number:
            errors.append("Informe o ciclo.")
        if not cycle_day:
            errors.append("Informe o D do ciclo.")
        if infusion_minutes <= 0:
            errors.append("Informe um tempo de infusão maior que zero.")
        if end_dt <= start_dt:
            errors.append("A data/hora final precisa ser maior que a inicial.")
        if errors:
            for error in errors:
                st.error(error)
            return

        box_conflicts, patient_conflicts = find_time_conflicts(
            patient_id=patient_id,
            box_id=box_id,
            start_dt=start_dt,
            end_dt=end_dt,
        )
        duplicate_d, same_date_other_day = find_cycle_conflicts(
            patient_id=patient_id,
            protocol=protocol,
            cycle_number=cycle_number,
            cycle_day=cycle_day,
            selected_date=selected_date,
        )

        has_conflict = any(not df.empty for df in [box_conflicts, patient_conflicts, duplicate_d, same_date_other_day])
        if has_conflict:
            st.error("Conflito encontrado. O agendamento não foi salvo.")
            if not box_conflicts.empty:
                st.markdown("**Conflito no box:**")
                st.dataframe(format_appointment_table(box_conflicts), use_container_width=True, hide_index=True)
            if not patient_conflicts.empty:
                st.markdown("**Conflito de horário para o mesmo paciente:**")
                st.dataframe(format_appointment_table(patient_conflicts), use_container_width=True, hide_index=True)
            if not duplicate_d.empty:
                st.markdown("**Duplicidade do mesmo D do ciclo:**")
                st.dataframe(format_appointment_table(duplicate_d), use_container_width=True, hide_index=True)
            if not same_date_other_day.empty:
                st.markdown("**Outro D já agendado na mesma data para o mesmo protocolo/ciclo:**")
                st.dataframe(format_appointment_table(same_date_other_day), use_container_width=True, hide_index=True)
            return

        appointment_id = create_appointment(
            patient_id=patient_id,
            box_id=box_id,
            start_dt=start_dt,
            end_dt=end_dt,
            infusion_minutes=infusion_minutes,
            status=status,
            protocol=protocol,
            medication=medication,
            cycle_number=cycle_number,
            cycle_day=cycle_day,
            responsible_team=responsible_team,
            notes=notes,
        )
        st.success(f"Agendamento #{appointment_id} salvo sem conflito. Fechou ✅")
        st.rerun()


def parse_optional_date(value: str | None) -> Optional[date]:
    raw = normalize_text(value)
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def import_patients_csv(df: pd.DataFrame, *, update_existing: bool, create_missing_health_plans: bool) -> dict:
    required = {"nome", "sistema_prontuario", "prontuario", "convenio"}
    missing = sorted(required - set(df.columns))
    if missing:
        return {"created": 0, "updated": 0, "errors": [{"linha": 0, "erro": f"Colunas ausentes: {', '.join(missing)}"}]}

    created = 0
    updated = 0
    errors = []
    current_plans = {normalize_key(x) for x in get_active_health_plans()["name"].tolist()}

    for idx, row in df.iterrows():
        line = int(idx) + 2
        try:
            name = normalize_text(row.get("nome", ""))
            record_system = normalize_key(row.get("sistema_prontuario", ""))
            medical_record = normalize_key(row.get("prontuario", ""))
            health_plan = normalize_key(row.get("convenio", ""))
            birthdate = parse_optional_date(str(row.get("data_nascimento", "")))
            phone = normalize_text(row.get("telefone", ""))
            notes = normalize_text(row.get("observacoes", ""))

            if not name:
                raise ValueError("Nome vazio")
            if record_system not in [normalize_key(x) for x in RECORD_SYSTEM_OPTIONS]:
                raise ValueError("Sistema de prontuário inválido. Use Tasy ou MV")
            if not medical_record:
                raise ValueError("Prontuário vazio")
            if not health_plan:
                raise ValueError("Convênio vazio")
            if health_plan not in current_plans:
                if create_missing_health_plans:
                    ensure_health_plan(health_plan)
                    current_plans.add(health_plan)
                else:
                    raise ValueError(f"Convênio não cadastrado: {health_plan}")

            existing = find_patient_by_record(record_system, medical_record)
            if existing:
                if not update_existing:
                    raise ValueError(f"Paciente já existe: {existing['name']} (ID {existing['id']})")
                update_patient(
                    patient_id=int(existing["id"]),
                    name=name,
                    record_system=record_system,
                    medical_record=medical_record,
                    birthdate=birthdate,
                    health_plan=health_plan,
                    phone=phone,
                    notes=notes,
                )
                updated += 1
            else:
                create_patient(
                    name=name,
                    record_system=record_system,
                    medical_record=medical_record,
                    birthdate=birthdate,
                    health_plan=health_plan,
                    phone=phone,
                    notes=notes,
                )
                created += 1
        except Exception as exc:  # noqa: BLE001
            errors.append({"linha": line, "erro": str(exc)})
    return {"created": created, "updated": updated, "errors": errors}


def render_patients() -> None:
    st.markdown("### 👤 Pacientes")
    health_plans_df = get_active_health_plans()
    health_plan_options = health_plans_df["name"].tolist() if not health_plans_df.empty else DEFAULT_HEALTH_PLANS
    patients_df = get_active_patients()

    tab_new, tab_edit, tab_import, tab_list = st.tabs(["➕ Cadastrar", "✏️ Editar", "⬆️ Importar CSV", "📋 Base"])

    with tab_new:
        with st.form("patient_form", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)
            with col1:
                name = st.text_input("Nome do paciente *")
                birthdate_enabled = st.checkbox("Informar data de nascimento")
                birthdate_value = st.date_input("Data de nascimento", value=date(1980, 1, 1), format="DD/MM/YYYY", disabled=not birthdate_enabled)
            with col2:
                record_system = st.selectbox("Sistema do prontuário *", RECORD_SYSTEM_OPTIONS)
                medical_record = st.text_input("Código do prontuário *", placeholder="Ex.: 123456")
            with col3:
                health_plan = st.selectbox("Convênio *", health_plan_options)
                phone = st.text_input("Telefone")
            notes = st.text_area("Observações clínicas/operacionais")
            submitted = st.form_submit_button("Cadastrar paciente")

        if submitted:
            errors = []
            if not normalize_text(name):
                errors.append("Informe o nome do paciente.")
            if not normalize_text(medical_record):
                errors.append("Informe o código do prontuário.")
            if not normalize_text(health_plan):
                errors.append("Informe o convênio.")
            existing = None
            if not errors:
                existing = find_patient_by_record(record_system, medical_record)
                if existing:
                    errors.append(f"Já existe paciente cadastrado com {record_system} / {medical_record}: {existing['name']} (ID {existing['id']}).")
            if errors:
                for error in errors:
                    st.error(error)
            else:
                try:
                    patient_id = create_patient(
                        name=name,
                        record_system=record_system,
                        medical_record=medical_record,
                        birthdate=birthdate_value if birthdate_enabled else None,
                        health_plan=health_plan,
                        phone=phone,
                        notes=notes,
                    )
                    st.success(f"Paciente #{patient_id} cadastrado.")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Duplicidade de prontuário encontrada. Esse paciente não foi salvo.")

    with tab_edit:
        if patients_df.empty:
            st.info("Nenhum paciente cadastrado para editar.")
        else:
            patient_options = {
                f"#{int(row['id'])} | {row['name']} | {row['record_system']} {row['medical_record']} | {row['health_plan']}": int(row["id"])
                for _, row in patients_df.iterrows()
            }
            selected_patient_label = st.selectbox("Selecione o paciente", list(patient_options.keys()), key="edit_patient_select")
            patient_id = patient_options[selected_patient_label]
            patient = get_patient_by_id(patient_id)
            if patient:
                current_birthdate = parse_optional_date(patient["birthdate"]) if patient["birthdate"] else None
                with st.form(f"edit_patient_form_{patient_id}"):
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        edit_name = st.text_input("Nome do paciente *", value=patient["name"] or "")
                        edit_birth_enabled = st.checkbox("Informar data de nascimento", value=current_birthdate is not None, key=f"birth_enabled_{patient_id}")
                        edit_birthdate = st.date_input(
                            "Data de nascimento",
                            value=current_birthdate or date(1980, 1, 1),
                            format="DD/MM/YYYY",
                            disabled=not edit_birth_enabled,
                            key=f"birthdate_{patient_id}",
                        )
                    with col2:
                        record_default = RECORD_SYSTEM_OPTIONS.index(patient["record_system"]) if patient["record_system"] in RECORD_SYSTEM_OPTIONS else 0
                        edit_record_system = st.selectbox("Sistema do prontuário *", RECORD_SYSTEM_OPTIONS, index=record_default)
                        edit_medical_record = st.text_input("Código do prontuário *", value=patient["medical_record"] or "")
                    with col3:
                        plan_default = health_plan_options.index(patient["health_plan"]) if patient["health_plan"] in health_plan_options else 0
                        edit_health_plan = st.selectbox("Convênio *", health_plan_options, index=plan_default)
                        edit_phone = st.text_input("Telefone", value=patient["phone"] or "")
                    edit_notes = st.text_area("Observações clínicas/operacionais", value=patient["notes"] or "")
                    c1, c2 = st.columns(2)
                    save_patient = c1.form_submit_button("Salvar alterações", type="primary", use_container_width=True)
                    deactivate = c2.form_submit_button("Inativar paciente", use_container_width=True)

                if save_patient:
                    errors = []
                    if not normalize_text(edit_name):
                        errors.append("Informe o nome do paciente.")
                    if not normalize_text(edit_medical_record):
                        errors.append("Informe o código do prontuário.")
                    if not normalize_text(edit_health_plan):
                        errors.append("Informe o convênio.")
                    existing = find_patient_by_record_except(edit_record_system, edit_medical_record, patient_id) if not errors else None
                    if existing:
                        errors.append(f"Outro paciente já usa {edit_record_system} / {edit_medical_record}: {existing['name']} (ID {existing['id']}).")
                    if errors:
                        for error in errors:
                            st.error(error)
                    else:
                        update_patient(
                            patient_id=patient_id,
                            name=edit_name,
                            record_system=edit_record_system,
                            medical_record=edit_medical_record,
                            birthdate=edit_birthdate if edit_birth_enabled else None,
                            health_plan=edit_health_plan,
                            phone=edit_phone,
                            notes=edit_notes,
                        )
                        st.success("Paciente atualizado.")
                        st.rerun()
                if deactivate:
                    deactivate_patient(patient_id)
                    st.warning("Paciente inativado. Agendamentos antigos permanecem na base.")
                    st.rerun()

    with tab_import:
        st.markdown(
            """
            <div class="hint">
            Modelo de pacientes: <b>nome, sistema_prontuario, prontuario, convenio, data_nascimento, telefone, observacoes</b>.<br>
            A data de nascimento aceita <b>AAAA-MM-DD</b> ou <b>DD/MM/AAAA</b>. O importador valida duplicidade por <b>sistema + prontuário</b>.
            </div>
            """,
            unsafe_allow_html=True,
        )
        template = pd.DataFrame(
            [
                {
                    "nome": "Paciente Exemplo",
                    "sistema_prontuario": "Tasy",
                    "prontuario": "123456",
                    "convenio": "AMIL",
                    "data_nascimento": "1980-01-01",
                    "telefone": "",
                    "observacoes": "",
                }
            ]
        )
        st.download_button(
            "⬇️ Baixar modelo CSV de pacientes",
            data=template.to_csv(index=False).encode("utf-8-sig"),
            file_name="modelo_importacao_pacientes_oncoflow.csv",
            mime="text/csv",
        )
        col_a, col_b = st.columns(2)
        update_existing = col_a.checkbox("Atualizar paciente existente se prontuário já existir", value=False)
        create_missing_plans = col_b.checkbox("Criar convênios ausentes automaticamente", value=True)
        uploaded_patients = st.file_uploader("Importar CSV de pacientes", type=["csv"], key="patients_csv")
        if uploaded_patients is not None:
            import_df = pd.read_csv(uploaded_patients)
            st.dataframe(import_df, use_container_width=True, hide_index=True)
            if st.button("Validar e importar pacientes", type="primary"):
                result = import_patients_csv(import_df, update_existing=update_existing, create_missing_health_plans=create_missing_plans)
                if result["errors"]:
                    st.error("Algumas linhas não foram importadas/atualizadas.")
                    for error in result["errors"]:
                        st.write(f"- Linha {error['linha']}: {error['erro']}")
                if result["created"] or result["updated"]:
                    st.success(f"{result['created']} paciente(s) criado(s) e {result['updated']} atualizado(s).")
                    st.rerun()

    with tab_list:
        patients_df = get_active_patients()
        if patients_df.empty:
            st.info("Nenhum paciente cadastrado ainda.")
        else:
            view = patients_df.rename(
                columns={
                    "id": "ID",
                    "name": "Paciente",
                    "record_system": "Sistema",
                    "medical_record": "Prontuário",
                    "birthdate": "Nascimento",
                    "health_plan": "Convênio",
                    "phone": "Telefone",
                    "notes": "Observações",
                }
            )
            st.dataframe(view, use_container_width=True, hide_index=True)
            st.download_button(
                "⬇️ Exportar pacientes em Excel",
                data=df_to_excel_bytes(view, "Pacientes"),
                file_name="pacientes_oncoflow.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )


def render_boxes() -> None:
    st.markdown("### 🧪 Boxes")
    with st.form("box_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Nome do box", placeholder="Ex.: Box 25")
        with col2:
            location = st.text_input("Local", value="Infusão")
        submitted = st.form_submit_button("Cadastrar box")

    if submitted:
        if not normalize_text(name):
            st.error("Informe o nome do box.")
        else:
            try:
                box_id = create_box(name, location)
                st.success(f"Box #{box_id} cadastrado.")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("Já existe um box com esse nome.")

    boxes_df = get_active_boxes()
    if boxes_df.empty:
        st.info("Nenhum box cadastrado ainda.")
    else:
        st.dataframe(
            boxes_df.rename(columns={"id": "ID", "name": "Box", "location": "Local"}),
            use_container_width=True,
            hide_index=True,
        )


def render_health_plans() -> None:
    st.markdown("### 🏥 Convênios")
    with st.form("health_plan_form", clear_on_submit=True):
        name = st.text_input("Novo convênio", placeholder="Ex.: MEDSÊNIOR")
        submitted = st.form_submit_button("Cadastrar convênio")
    if submitted:
        if not normalize_text(name):
            st.error("Informe o nome do convênio.")
        else:
            try:
                plan_id = create_health_plan(name)
                st.success(f"Convênio #{plan_id} cadastrado.")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("Já existe um convênio com esse nome.")

    plans_df = get_active_health_plans()
    st.dataframe(plans_df.rename(columns={"id": "ID", "name": "Convênio"}), use_container_width=True, hide_index=True)


def render_manage_appointments() -> None:
    st.markdown("### 🛠️ Gerenciar / editar agendamentos")
    future_df = get_all_future_appointments(limit=1000)
    if future_df.empty:
        st.info("Nenhum agendamento futuro encontrado.")
        return

    formatted = format_appointment_table(future_df)
    st.dataframe(formatted, use_container_width=True, hide_index=True)

    options = {
        f"#{int(row['id'])} | {row['paciente']} | {row['ciclo'] or ''} {row['ciclo_dia'] or ''} | {pd.to_datetime(row['inicio']).strftime('%d/%m %H:%M')} | {row['box']} | {row['status']}": int(row["id"])
        for _, row in future_df.iterrows()
    }
    selected_label = st.selectbox("Selecione um agendamento para editar", list(options.keys()))
    appointment_id = options[selected_label]
    appointment = get_appointment_by_id(appointment_id)
    if not appointment:
        st.error("Agendamento não encontrado.")
        return

    patients_df = get_active_patients()
    boxes_df = get_active_boxes()
    patient_options = {
        f"{row['name']} | {row['record_system'] or 'SIST?'} {row['medical_record'] or 'SEM PRONT.'} | {row['health_plan'] or 'Sem convênio'} | ID {row['id']}": int(row["id"])
        for _, row in patients_df.iterrows()
    }
    box_options = {f"{row['name']} | {row['location'] or 'Sem local'}": int(row["id"]) for _, row in boxes_df.iterrows()}
    patient_labels = list(patient_options.keys())
    box_labels = list(box_options.keys())
    patient_index = next((i for i, label in enumerate(patient_labels) if patient_options[label] == int(appointment["patient_id"])), 0)
    box_index = next((i for i, label in enumerate(box_labels) if box_options[label] == int(appointment["box_id"])), 0)

    start_current = parse_iso(appointment["start_datetime"])
    infusion_current = int(appointment["infusion_minutes"] or max(0, (parse_iso(appointment["end_datetime"]) - start_current).total_seconds() // 60))
    duration_index = INFUSION_DURATION_OPTIONS.index(infusion_current) if infusion_current in INFUSION_DURATION_OPTIONS else 4
    custom_default = 0 if infusion_current in INFUSION_DURATION_OPTIONS else infusion_current
    status_index = STATUS_OPTIONS.index(appointment["status"]) if appointment["status"] in STATUS_OPTIONS else 0
    cycle_index = CYCLE_NUMBER_OPTIONS.index(appointment["cycle_number"]) if appointment["cycle_number"] in CYCLE_NUMBER_OPTIONS else 0
    cycle_day_value = appointment["cycle_day"] or "D1"
    cycle_day_index = CYCLE_DAY_OPTIONS.index(cycle_day_value) if cycle_day_value in CYCLE_DAY_OPTIONS else CYCLE_DAY_OPTIONS.index("Outro")

    with st.form(f"edit_appointment_form_{appointment_id}"):
        st.markdown(f"#### Editando agendamento #{appointment_id}")
        col1, col2, col3 = st.columns(3)
        with col1:
            patient_label = st.selectbox("Paciente *", patient_labels, index=patient_index)
            box_label = st.selectbox("Box *", box_labels, index=box_index)
            selected_date = st.date_input("Data *", value=start_current.date(), format="DD/MM/YYYY")
            start_time = st.time_input("Horário de início *", value=start_current.time().replace(second=0, microsecond=0), step=timedelta(minutes=15))
        with col2:
            selected_duration = st.selectbox("Tempo de infusão previsto *", INFUSION_DURATION_OPTIONS, index=duration_index, format_func=human_duration_minutes)
            custom_duration = st.number_input("Ou informe outro tempo em minutos", min_value=0, max_value=720, value=int(custom_default), step=15)
            status = st.selectbox("Status", STATUS_OPTIONS, index=status_index)
            responsible_team = st.text_input("Equipe responsável", value=appointment["responsible_team"] or "")
        with col3:
            protocol = st.text_input("Protocolo/Pedido *", value=appointment["protocol"] or "")
            medication = st.text_input("Medicamento / esquema", value=appointment["medication"] or "")
            cycle_number = st.selectbox("Ciclo *", CYCLE_NUMBER_OPTIONS, index=cycle_index)
            cycle_day_choice = st.selectbox("D do ciclo *", CYCLE_DAY_OPTIONS, index=cycle_day_index)
            cycle_day_custom = st.text_input(
                "Se Outro, informe o D",
                value=cycle_day_value if cycle_day_choice == "Outro" else "",
                placeholder="Ex.: D10",
                disabled=cycle_day_choice != "Outro",
            )
        notes = st.text_area("Observações", value=appointment["notes"] or "")
        c1, c2 = st.columns(2)
        submitted = c1.form_submit_button("Salvar alterações do agendamento", type="primary", use_container_width=True)
        delete_submitted = c2.form_submit_button("Excluir agendamento", use_container_width=True)

    if submitted:
        patient_id = patient_options[patient_label]
        box_id = box_options[box_label]
        infusion_minutes = int(custom_duration or selected_duration)
        cycle_day = cycle_day_custom if cycle_day_choice == "Outro" else cycle_day_choice
        cycle_day = normalize_cycle_day(cycle_day)
        cycle_number = normalize_cycle_number(cycle_number)
        protocol = normalize_key(protocol)
        start_dt = datetime.combine(selected_date, start_time)
        end_dt = start_dt + timedelta(minutes=infusion_minutes)

        errors, conflicts = validate_appointment_rules(
            patient_id=patient_id,
            box_id=box_id,
            start_dt=start_dt,
            end_dt=end_dt,
            infusion_minutes=infusion_minutes,
            protocol=protocol,
            cycle_number=cycle_number,
            cycle_day=cycle_day,
            ignore_appointment_id=appointment_id,
        )
        if not show_appointment_validation_result(errors, conflicts):
            return

        update_appointment(
            appointment_id=appointment_id,
            patient_id=patient_id,
            box_id=box_id,
            start_dt=start_dt,
            end_dt=end_dt,
            infusion_minutes=infusion_minutes,
            status=status,
            protocol=protocol,
            medication=medication,
            cycle_number=cycle_number,
            cycle_day=cycle_day,
            responsible_team=responsible_team,
            notes=notes,
        )
        log_appointment_event(
            appointment_id=appointment_id,
            event_type="Agendamento editado",
            event_datetime=now_iso(),
            user_name="Gerenciar agendamento",
            notes=f"Agendamento atualizado. Status salvo: {status}",
            update_status=False,
        )
        st.success("Agendamento atualizado sem conflito.")
        st.rerun()

    if delete_submitted:
        delete_appointment(appointment_id)
        st.warning("Agendamento excluído.")
        st.rerun()


def render_import_export() -> None:
    st.markdown("### ⬆️ Importação de agenda e exportação")
    st.markdown(
        """
        <div class="hint">
        Modelo de importação: <b>paciente, sistema_prontuario, prontuario, convenio, box, data, inicio, tempo_infusao_min, status, protocolo, medicamento, ciclo, ciclo_dia, equipe, observacoes</b>.<br>
        Data em <b>AAAA-MM-DD</b> e início em <b>HH:MM</b>. O importador aplica as mesmas travas de conflito da tela.
        </div>
        """,
        unsafe_allow_html=True,
    )

    template = pd.DataFrame(
        [
            {
                "paciente": "Paciente Exemplo",
                "sistema_prontuario": "Tasy",
                "prontuario": "123456",
                "convenio": "AMIL",
                "box": "Box 01",
                "data": date.today().isoformat(),
                "inicio": "08:00",
                "tempo_infusao_min": 120,
                "status": "Agendado",
                "protocolo": "PED-001",
                "medicamento": "Paclitaxel",
                "ciclo": "C1",
                "ciclo_dia": "D1",
                "equipe": "Navegação",
                "observacoes": "Exemplo de importação",
            }
        ]
    )
    st.download_button(
        "⬇️ Baixar modelo CSV",
        data=template.to_csv(index=False).encode("utf-8-sig"),
        file_name="modelo_importacao_agenda_boxes.csv",
        mime="text/csv",
    )

    uploaded = st.file_uploader("Importar CSV", type=["csv"])
    if uploaded is not None:
        import_df = pd.read_csv(uploaded)
        st.dataframe(import_df, use_container_width=True, hide_index=True)
        if st.button("Validar e importar CSV"):
            result = import_csv(import_df)
            if result["errors"]:
                st.error("Algumas linhas não foram importadas.")
                for error in result["errors"]:
                    st.write(f"- Linha {error['linha']}: {error['erro']}")
            if result["created"]:
                st.success(f"{result['created']} agendamentos importados com sucesso.")
                st.rerun()

    all_df = read_df(
        """
        SELECT
            a.id,
            p.name AS paciente,
            p.record_system AS sistema_prontuario,
            p.medical_record AS prontuario,
            p.health_plan AS convenio,
            b.name AS box,
            a.start_datetime AS inicio,
            a.end_datetime AS fim,
            a.infusion_minutes AS tempo_infusao_min,
            a.status,
            a.protocol AS protocolo,
            a.medication AS medicamento,
            a.cycle_number AS ciclo,
            a.cycle_day AS ciclo_dia,
            a.responsible_team AS equipe,
            a.notes AS observacoes
        FROM appointments a
        JOIN patients p ON p.id = a.patient_id
        JOIN boxes b ON b.id = a.box_id
        ORDER BY a.start_datetime DESC
        """
    )
    if not all_df.empty:
        formatted = format_appointment_table(all_df)
        st.download_button(
            "⬇️ Exportar base completa em Excel",
            data=df_to_excel_bytes(formatted, "Base completa"),
            file_name="base_agenda_boxes_oncoflow.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


def get_or_create_patient_by_record(name: str, record_system: str, medical_record: str, health_plan: str = "") -> int:
    existing = find_patient_by_record(record_system, medical_record)
    if existing:
        return int(existing["id"])
    return create_patient(
        name=name,
        record_system=record_system,
        medical_record=medical_record,
        birthdate=None,
        health_plan=health_plan,
        phone="",
        notes="Criado via importação",
    )


def get_box_by_name(name: str) -> Optional[int]:
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT id FROM boxes WHERE lower(trim(name)) = lower(trim(?)) AND active = 1 LIMIT 1",
            (name,),
        ).fetchone()
        return int(row["id"]) if row else None


def import_csv(df: pd.DataFrame) -> dict:
    required = {"paciente", "sistema_prontuario", "prontuario", "convenio", "box", "data", "inicio", "tempo_infusao_min", "protocolo", "ciclo", "ciclo_dia"}
    missing = sorted(required - set(df.columns))
    if missing:
        return {"created": 0, "errors": [{"linha": 0, "erro": f"Colunas ausentes: {', '.join(missing)}"}]}

    created = 0
    errors = []
    for idx, row in df.iterrows():
        line = int(idx) + 2
        try:
            patient_name = normalize_text(row.get("paciente", ""))
            record_system = normalize_key(row.get("sistema_prontuario", ""))
            medical_record = normalize_key(row.get("prontuario", ""))
            health_plan = normalize_key(row.get("convenio", ""))
            box_name = normalize_text(row.get("box", ""))
            protocol = normalize_key(row.get("protocolo", ""))
            cycle_number = normalize_cycle_number(row.get("ciclo", ""))
            cycle_day = normalize_cycle_day(row.get("ciclo_dia", ""))

            if not patient_name:
                raise ValueError("Paciente vazio")
            if record_system not in [normalize_key(x) for x in RECORD_SYSTEM_OPTIONS]:
                raise ValueError("Sistema de prontuário inválido. Use Tasy ou MV")
            if not medical_record:
                raise ValueError("Prontuário vazio")
            if not health_plan:
                raise ValueError("Convênio vazio")
            if not box_name:
                raise ValueError("Box vazio")
            if not protocol:
                raise ValueError("Protocolo/Pedido vazio")
            if not cycle_number:
                raise ValueError("Ciclo vazio")
            if not cycle_day:
                raise ValueError("D do ciclo vazio")

            box_id = get_box_by_name(box_name)
            if not box_id:
                raise ValueError(f"Box não encontrado: {box_name}")

            patient_id = get_or_create_patient_by_record(patient_name, record_system, medical_record, health_plan)
            start_date = datetime.strptime(str(row["data"]), "%Y-%m-%d").date()
            start_clock = datetime.strptime(str(row["inicio"]), "%H:%M").time()
            infusion_minutes = int(row["tempo_infusao_min"])
            start_dt = datetime.combine(start_date, start_clock)
            end_dt = start_dt + timedelta(minutes=infusion_minutes)

            box_conflicts, patient_conflicts = find_time_conflicts(
                patient_id=patient_id,
                box_id=box_id,
                start_dt=start_dt,
                end_dt=end_dt,
            )
            duplicate_d, same_date_other_day = find_cycle_conflicts(
                patient_id=patient_id,
                protocol=protocol,
                cycle_number=cycle_number,
                cycle_day=cycle_day,
                selected_date=start_date,
            )
            if not box_conflicts.empty:
                raise ValueError("Conflito de box")
            if not patient_conflicts.empty:
                raise ValueError("Conflito de horário para o mesmo paciente")
            if not duplicate_d.empty:
                raise ValueError("Duplicidade do mesmo D do ciclo")
            if not same_date_other_day.empty:
                raise ValueError("Outro D já existe na mesma data para o mesmo protocolo/ciclo")

            create_appointment(
                patient_id=patient_id,
                box_id=box_id,
                start_dt=start_dt,
                end_dt=end_dt,
                infusion_minutes=infusion_minutes,
                status=normalize_text(row.get("status", "Agendado")) or "Agendado",
                protocol=protocol,
                medication=normalize_text(row.get("medicamento", "")),
                cycle_number=cycle_number,
                cycle_day=cycle_day,
                responsible_team=normalize_text(row.get("equipe", "")),
                notes=normalize_text(row.get("observacoes", "")),
            )
            created += 1
        except Exception as exc:  # noqa: BLE001 - exibir erro amigável por linha
            errors.append({"linha": line, "erro": str(exc)})
    return {"created": created, "errors": errors}



def format_event_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    for col in ["inicio_previsto", "fim_previsto", "quando", "registrado_em"]:
        if col in out.columns:
            out[col] = pd.to_datetime(out[col]).dt.strftime("%d/%m/%Y %H:%M")
    return out.rename(
        columns={
            "id": "ID Evento",
            "appointment_id": "ID Agendamento",
            "paciente": "Paciente",
            "sistema_prontuario": "Sistema",
            "prontuario": "Prontuário",
            "convenio": "Convênio",
            "box": "Box",
            "inicio_previsto": "Início previsto",
            "fim_previsto": "Fim previsto",
            "status_atual": "Status atual",
            "protocolo": "Protocolo/Pedido",
            "ciclo": "Ciclo",
            "ciclo_dia": "D do ciclo",
            "evento": "Evento",
            "quando": "Quando ocorreu",
            "usuario": "Responsável/usuário",
            "observacoes": "Observações",
            "registrado_em": "Registrado em",
        }
    )


def first_event_time(events: pd.DataFrame, appointment_id: int, event_names: list[str]) -> Optional[datetime]:
    subset = events[(events["appointment_id"] == appointment_id) & (events["evento"].isin(event_names))].copy()
    if subset.empty:
        return None
    return pd.to_datetime(subset["quando"]).min().to_pydatetime()


def count_events(events: pd.DataFrame, appointment_id: int, event_names: list[str]) -> int:
    return int(((events["appointment_id"] == appointment_id) & (events["evento"].isin(event_names))).sum())


def calc_pause_minutes(events: pd.DataFrame, appointment_id: int) -> int:
    subset = events[events["appointment_id"] == appointment_id].copy()
    if subset.empty:
        return 0
    subset["dt"] = pd.to_datetime(subset["quando"])
    subset = subset.sort_values("dt")
    paused_at: Optional[datetime] = None
    total = 0
    for _, ev in subset.iterrows():
        name = str(ev["evento"])
        dt = ev["dt"].to_pydatetime()
        if name == "Infusão pausada por intercorrência" and paused_at is None:
            paused_at = dt
        elif name in ("Infusão retomada", "Infusão finalizada", "Paciente liberado") and paused_at is not None:
            total += max(0, int((dt - paused_at).total_seconds() // 60))
            paused_at = None
    return total


def build_operational_summary(start_filter: date, end_filter: date) -> pd.DataFrame:
    agenda = read_df(
        """
        SELECT
            a.id,
            p.name AS paciente,
            p.record_system AS sistema_prontuario,
            p.medical_record AS prontuario,
            p.health_plan AS convenio,
            b.name AS box,
            a.start_datetime AS inicio_previsto,
            a.end_datetime AS fim_previsto,
            a.infusion_minutes AS tempo_previsto_min,
            a.status AS status_atual,
            a.protocol AS protocolo,
            a.medication AS medicamento,
            a.cycle_number AS ciclo,
            a.cycle_day AS ciclo_dia,
            a.responsible_team AS equipe,
            a.notes AS observacoes
        FROM appointments a
        JOIN patients p ON p.id = a.patient_id
        JOIN boxes b ON b.id = a.box_id
        WHERE a.start_datetime >= ? AND a.start_datetime < ?
        ORDER BY a.start_datetime
        """,
        (
            datetime.combine(start_filter, time.min).isoformat(timespec="seconds"),
            datetime.combine(end_filter + timedelta(days=1), time.min).isoformat(timespec="seconds"),
        ),
    )
    if agenda.empty:
        return pd.DataFrame()

    events = get_appointment_events(start_date=start_filter, end_date=end_filter + timedelta(days=1))
    if events.empty:
        events = pd.DataFrame(columns=["appointment_id", "evento", "quando", "observacoes"])

    rows = []
    for _, appt in agenda.iterrows():
        appt_id = int(appt["id"])
        previsto_inicio = parse_iso(appt["inicio_previsto"])
        previsto_fim = parse_iso(appt["fim_previsto"])
        alocado = first_event_time(events, appt_id, ["Paciente alocado no box"])
        preqt_ini = first_event_time(events, appt_id, ["Pré-QT iniciada"])
        preqt_fim = first_event_time(events, appt_id, ["Pré-QT finalizada — aguardando medicamento da farmácia"])
        med_recebido = first_event_time(events, appt_id, ["Medicamento recebido da farmácia"])
        inf_ini = first_event_time(events, appt_id, ["Infusão iniciada", "Infusão em andamento"])
        inf_fim = first_event_time(events, appt_id, ["Infusão finalizada"])
        liberado = first_event_time(events, appt_id, ["Paciente liberado"])
        pause_min = calc_pause_minutes(events, appt_id)
        pause_count = count_events(events, appt_id, ["Infusão pausada por intercorrência"])
        intercorr_count = count_events(events, appt_id, ["Infusão pausada por intercorrência", "Intercorrência registrada"])

        def diff_minutes(a: Optional[datetime], b: Optional[datetime]) -> Optional[int]:
            if not a or not b:
                return None
            return int((b - a).total_seconds() // 60)

        duracao_real_inf = diff_minutes(inf_ini, inf_fim)
        duracao_real_sem_pausa = duracao_real_inf - pause_min if duracao_real_inf is not None else None
        espera_farmacia = diff_minutes(preqt_fim, med_recebido)
        atraso_inicio_inf = diff_minutes(previsto_inicio, inf_ini)
        permanencia_total = diff_minutes(alocado or previsto_inicio, liberado or inf_fim)

        notes_subset = events[(events["appointment_id"] == appt_id) & (events["observacoes"].notna())]
        resumo_obs = " | ".join(str(x) for x in notes_subset["observacoes"].tolist()[:5])

        rows.append(
            {
                "ID Agendamento": appt_id,
                "Paciente": appt["paciente"],
                "Sistema": appt["sistema_prontuario"],
                "Prontuário": appt["prontuario"],
                "Convênio": appt["convenio"],
                "Box": appt["box"],
                "Protocolo/Pedido": appt["protocolo"],
                "Medicamento": appt["medicamento"],
                "Ciclo": appt["ciclo"],
                "D do ciclo": appt["ciclo_dia"],
                "Status atual": appt["status_atual"],
                "Início previsto": previsto_inicio.strftime("%d/%m/%Y %H:%M"),
                "Fim previsto": previsto_fim.strftime("%d/%m/%Y %H:%M"),
                "Tempo previsto (min)": int(appt["tempo_previsto_min"] or 0),
                "Alocado no box em": alocado.strftime("%d/%m/%Y %H:%M") if alocado else "",
                "Pré-QT início": preqt_ini.strftime("%d/%m/%Y %H:%M") if preqt_ini else "",
                "Pré-QT fim / aguardando farmácia": preqt_fim.strftime("%d/%m/%Y %H:%M") if preqt_fim else "",
                "Medicamento recebido em": med_recebido.strftime("%d/%m/%Y %H:%M") if med_recebido else "",
                "Infusão início real": inf_ini.strftime("%d/%m/%Y %H:%M") if inf_ini else "",
                "Infusão fim real": inf_fim.strftime("%d/%m/%Y %H:%M") if inf_fim else "",
                "Paciente liberado em": liberado.strftime("%d/%m/%Y %H:%M") if liberado else "",
                "Espera farmácia (min)": espera_farmacia,
                "Atraso início infusão vs previsto (min)": atraso_inicio_inf,
                "Duração real infusão bruta (min)": duracao_real_inf,
                "Total pausa/intercorrência (min)": pause_min,
                "Duração real infusão sem pausas (min)": duracao_real_sem_pausa,
                "Qtd pausas": pause_count,
                "Qtd intercorrências": intercorr_count,
                "Permanência total no box/atendimento (min)": permanencia_total,
                "Observações dos eventos": resumo_obs,
            }
        )
    return pd.DataFrame(rows)


def operational_report_excel_bytes(summary_df: pd.DataFrame, events_df: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        summary_df.to_excel(writer, index=False, sheet_name="Resumo operacional")
        format_event_table(events_df).to_excel(writer, index=False, sheet_name="Linha do tempo")
    return buffer.getvalue()


def render_operational_report() -> None:
    st.markdown("### 🧾 Relatório operacional / linha do tempo")
    st.markdown(
        """
        <div class="hint">
        Cada evento registrado na agenda vira histórico auditável do atendimento: alocação, pré-QT, espera da farmácia,
        início/fim real da infusão, pausas por intercorrência e liberação do paciente.
        </div>
        """,
        unsafe_allow_html=True,
    )
    col1, col2 = st.columns(2)
    start_filter = col1.date_input("Data inicial", value=date.today(), format="DD/MM/YYYY", key="report_start")
    end_filter = col2.date_input("Data final", value=date.today(), format="DD/MM/YYYY", key="report_end")
    if end_filter < start_filter:
        st.error("Data final precisa ser maior ou igual à data inicial.")
        return

    summary_df = build_operational_summary(start_filter, end_filter)
    events_df = get_appointment_events(start_date=start_filter, end_date=end_filter)

    if summary_df.empty:
        st.info("Nenhum agendamento encontrado no período.")
        return

    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("Agendamentos", len(summary_df))
    col_b.metric("Infusões iniciadas", int((summary_df["Infusão início real"] != "").sum()))
    col_c.metric("Infusões finalizadas", int((summary_df["Infusão fim real"] != "").sum()))
    col_d.metric("Intercorrências", int(summary_df["Qtd intercorrências"].fillna(0).sum()))

    st.markdown("#### Resumo por agendamento")
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    st.markdown("#### Linha do tempo dos eventos")
    st.dataframe(format_event_table(events_df), use_container_width=True, hide_index=True)

    st.download_button(
        "⬇️ Baixar relatório operacional em Excel",
        data=operational_report_excel_bytes(summary_df, events_df),
        file_name=f"relatorio_operacional_agenda_boxes_{start_filter.isoformat()}_{end_filter.isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="🧪", layout="wide")
    init_db()
    seed_boxes_if_empty(DEFAULT_BOXES)
    seed_health_plans_if_empty()
    apply_css()
    render_header()

    selected_date, open_time, close_time, slot_minutes = render_sidebar()
    if close_time <= open_time:
        st.error("O horário de fechamento precisa ser maior que o horário de abertura.")
        return

    tab_dashboard, tab_new, tab_patients, tab_boxes, tab_plans, tab_manage, tab_report, tab_import = st.tabs(
        [
            "📊 Agenda do dia",
            "➕ Novo agendamento",
            "👤 Pacientes",
            "🧪 Boxes",
            "🏥 Convênios",
            "🛠️ Gerenciar",
            "🧾 Relatório operacional",
            "⬆️ Importar/Exportar",
        ]
    )

    with tab_dashboard:
        render_dashboard(selected_date, open_time, close_time, slot_minutes)
    with tab_new:
        render_new_appointment()
    with tab_patients:
        render_patients()
    with tab_boxes:
        render_boxes()
    with tab_plans:
        render_health_plans()
    with tab_manage:
        render_manage_appointments()
    with tab_report:
        render_operational_report()
    with tab_import:
        render_import_export()


if __name__ == "__main__":
    main()
