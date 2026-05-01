-- Nexus AI — Supabase Database Schema
-- Run this in the Supabase SQL Editor (Dashboard -> SQL Editor -> New Query)

-- Profiles (auto-created on signup via trigger)
create table if not exists profiles (
  id uuid references auth.users on delete cascade primary key,
  email text,
  display_name text,
  avatar_url text,
  created_at timestamptz default now()
);

-- Projects
create table if not exists projects (
  id text primary key,
  user_id uuid references profiles(id) on delete cascade not null,
  name text not null,
  prompt text not null,
  status text default 'created',
  workspace_path text,
  published_url text,
  framework text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- Messages (chat history)
create table if not exists messages (
  id bigserial primary key,
  project_id text references projects(id) on delete cascade not null,
  role text not null,
  agent_name text,
  content text,
  created_at timestamptz default now()
);

-- Generated files
create table if not exists files (
  id bigserial primary key,
  project_id text references projects(id) on delete cascade not null,
  path text not null,
  content text,
  size integer default 0,
  updated_at timestamptz default now(),
  unique(project_id, path)
);

-- Enable Row Level Security
alter table profiles enable row level security;
alter table projects enable row level security;
alter table messages enable row level security;
alter table files enable row level security;

-- RLS Policies
create policy "Users read own profile" on profiles for select using (auth.uid() = id);
create policy "Users update own profile" on profiles for update using (auth.uid() = id);
create policy "Users read own projects" on projects for select using (auth.uid() = user_id);
create policy "Users insert own projects" on projects for insert with check (auth.uid() = user_id);
create policy "Users update own projects" on projects for update using (auth.uid() = user_id);
create policy "Users delete own projects" on projects for delete using (auth.uid() = user_id);
create policy "Users read own messages" on messages for select using (
  project_id in (select id from projects where user_id = auth.uid())
);
create policy "Users insert own messages" on messages for insert with check (
  project_id in (select id from projects where user_id = auth.uid())
);
create policy "Users read own files" on files for select using (
  project_id in (select id from projects where user_id = auth.uid())
);
create policy "Users insert own files" on files for insert with check (
  project_id in (select id from projects where user_id = auth.uid())
);

-- Auto-create profile on signup
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, email, display_name)
  values (
    new.id,
    new.raw_user_meta_data ->> 'email',
    coalesce(
      new.raw_user_meta_data ->> 'full_name',
      new.raw_user_meta_data ->> 'name',
      split_part(new.raw_user_meta_data ->> 'email', '@', 1)
    )
  );
  return new;
exception when others then
  raise log 'handle_new_user failed: %', sqlerrm;
  return new;
end;
$$;

-- Drop trigger if exists and recreate
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- Create indexes for performance
create index if not exists idx_projects_user_id on projects(user_id);
create index if not exists idx_messages_project_id on messages(project_id);
create index if not exists idx_files_project_id on files(project_id);
