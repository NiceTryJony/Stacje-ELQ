-- Выполнить в Supabase SQL Editor перед первым запуском бота

create table if not exists stations (
    id bigint generated always as identity primary key,
    name text not null,
    address text,
    lat double precision not null,
    lng double precision not null,
    google_maps_url text,
    note text,
    created_at timestamptz not null default now()
);

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
