-- =========================================
-- SHS FINDER GH DATABASE
-- POSTGRESQL VERSION
-- =========================================


-- =========================
-- USERS TABLE
-- =========================

CREATE TABLE IF NOT EXISTS users (

    id SERIAL PRIMARY KEY,

    name VARCHAR(100) NOT NULL,

    phone VARCHAR(20) UNIQUE NOT NULL,

    password TEXT NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

);



-- =========================
-- SCHOOLS TABLE
-- =========================

CREATE TABLE IF NOT EXISTS schools (

    id SERIAL PRIMARY KEY,


    name VARCHAR(200) NOT NULL,


    region VARCHAR(100) NOT NULL,


    category VARCHAR(100) NOT NULL,


    gender VARCHAR(30) NOT NULL,


    location VARCHAR(200),


    description TEXT,


    courses TEXT,


    image TEXT,


    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

);





-- =========================
-- ADMIN TABLE
-- =========================

CREATE TABLE IF NOT EXISTS admins (

    id SERIAL PRIMARY KEY,

    username VARCHAR(50) UNIQUE NOT NULL,

    password TEXT NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

);




-- =========================
-- GHANA SHS DATA
-- =========================


INSERT INTO schools
(
name,
region,
category,
gender,
location,
description,
courses,
image
)

VALUES



(
"Achimota School",
"Greater Accra",
"Category A",
"Mixed",
"Achimota, Accra",
"One of Ghana's oldest and most respected senior high schools.",
"Science, Business, Arts, General Arts",
"https://images.unsplash.com/photo-1564981797816-1043664bf78d"
),



(
"Prempeh College",
"Ashanti",
"Category A",
"Boys",
"Kumasi",
"A leading boys senior high school in Ghana.",
"Science, Business, Arts",
"https://images.unsplash.com/photo-1523050854058-8df90110c9f1"
),



(
"Aburi Girls Senior High School",
"Eastern",
"Category A",
"Girls",
"Aburi",
"Popular girls school known for academic excellence.",
"Science, Business, Home Economics",
"https://images.unsplash.com/photo-1509062522246-3755977927d7"
),



(
"Mfantsipim School",
"Central",
"Category A",
"Boys",
"Cape Coast",
"Historic boys school producing great leaders.",
"Science, Business, Arts",
"https://images.unsplash.com/photo-1580582932707-520aed937b7b"
),



(
"Opoku Ware School",
"Ashanti",
"Category A",
"Boys",
"Kumasi",
"A top performing boys school.",
"Science, Business, Arts",
"https://images.unsplash.com/photo-1606761568499-6d2451b23c66"
),



(
"Holy Child School",
"Central",
"Category A",
"Girls",
"Cape Coast",
"Girls school with strong academic performance.",
"Science, Business, Arts",
"https://images.unsplash.com/photo-1523240795612-9a054b0db644"
),



(
"St. Peters Senior High School",
"Central",
"Category A",
"Boys",
"Nkwatia",
"Well known boys school in Ghana.",
"Science, Business, Arts",
"https://images.unsplash.com/photo-1541339907198-e08756dedf3f"
),



(
"Presbyterian Boys Senior High",
"Greater Accra",
"Category A",
"Boys",
"Legon",
"One of Ghana's top boys schools.",
"Science, Business, Arts",
"https://images.unsplash.com/photo-1503676260728-1c00da094a0b"
),



(
"Accra Girls Senior High School",
"Greater Accra",
"Category A",
"Girls",
"Accra",
"Leading girls school located in Accra.",
"Science, Business, Arts",
"https://images.unsplash.com/photo-1523580846011-d3a5bc25702b"
),



(
"Kwame Nkrumah University SHS",
"Ashanti",
"Category B",
"Mixed",
"Kumasi",
"Senior high school offering multiple programs.",
"Science, Business, Arts",
"https://images.unsplash.com/photo-1562774053-701939374585"
);






-- =========================
-- INDEXES
-- =========================


CREATE INDEX IF NOT EXISTS schools_region_idx
ON schools(region);



CREATE INDEX IF NOT EXISTS schools_category_idx
ON schools(category);



CREATE INDEX IF NOT EXISTS schools_gender_idx
ON schools(gender);



CREATE INDEX IF NOT EXISTS schools_name_idx
ON schools(name);



CREATE INDEX IF NOT EXISTS users_phone_idx
ON users(phone);





-- =========================
-- DEFAULT ADMIN
-- =========================

INSERT INTO admins
(
username,
password
)

VALUES
(
"admin",
"change_this_password"
)

ON CONFLICT DO NOTHING;



-- =========================
-- VIEW ALL REGIONS
-- =========================

CREATE TABLE IF NOT EXISTS regions (

id SERIAL PRIMARY KEY,

name VARCHAR(100) UNIQUE NOT NULL

);



INSERT INTO regions(name)
VALUES

('Greater Accra'),
('Ashanti'),
('Central'),
('Eastern'),
('Western'),
('Western North'),
('Volta'),
('Oti'),
('Northern'),
('Savannah'),
('North East'),
('Bono'),
('Bono East'),
('Ahafo'),
('Upper East'),
('Upper West')

ON CONFLICT DO NOTHING;




-- =========================
-- SCHOOL CATEGORIES
-- =========================

CREATE TABLE IF NOT EXISTS categories (

id SERIAL PRIMARY KEY,

name VARCHAR(100) UNIQUE NOT NULL

);



INSERT INTO categories(name)

VALUES

('Category A'),
('Category B'),
('Category C'),
('Category D')

ON CONFLICT DO NOTHING;
