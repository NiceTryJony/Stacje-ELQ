-- Выполнить в Supabase SQL Editor перед первым запуском бота

create extension if not exists pg_trgm;

create table if not exists stations (
    id bigint generated always as identity primary key,
    name text not null,
    address text,
    lat double precision not null,
    lng double precision not null,
    google_maps_url text,
    note text,
    note2 text,
    created_at timestamptz not null default now()
);

-- Если таблица уже существует с прошлого деплоя — выполни отдельно эту строку:
-- alter table stations add column if not exists note2 text;

-- Простой текстовый поиск по названию (для /find)
create index if not exists stations_name_trgm_idx
    on stations using gin (name gin_trgm_ops);

create table if not exists subscribers (
    chat_id bigint primary key,
    title text,
    added_at timestamptz not null default now()
);

create table if not exists bot_meta (
    key text primary key,
    value text
);

insert into bot_meta (key, value)
values ('last_activity_at', now()::text)
on conflict (key) do nothing;
