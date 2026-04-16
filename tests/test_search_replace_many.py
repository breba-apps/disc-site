import pytest

from breba_app.filesystem.in_memory_store import from_raw_strings
from breba_app.search_replace_editing import apply_search_replace_many, ApplyEditsError


@pytest.fixture
def search_replace_block():
    return """index.html
```html
<<<<<<< SEARCH
      <div class="collapse navbar-collapse" id="mainNavbar">
        <ul class="navbar-nav ms-auto mb-2 mb-lg-0 me-lg-3">
          <li class="nav-item">
            <a class="nav-link active" href="#hero" data-nav-target="hero">Главная</a>
          </li>
          <li class="nav-item">
            <a class="nav-link" href="#classes" data-nav-target="classes">Классы и расписание</a>
          </li>
          <li class="nav-item">
            <a class="nav-link" href="#mission" data-nav-target="mission">Миссия</a>
          </li>
          <li class="nav-item">
            <a class="nav-link" href="#philosophy" data-nav-target="philosophy">Философия обучения</a>
          </li>
          <li class="nav-item">
            <a class="nav-link" href="#testimonials" data-nav-target="testimonials">Отзывы</a>
          </li>
          <li class="nav-item">
            <a class="nav-link" href="#faq" data-nav-target="faq">FAQ</a>
          </li>
        </ul>
        <div class="d-flex align-items-center gap-2">
          <a href="https://www.facebook.com/groups/1411313069413512" class="navbar-social-link" target="_blank" rel="noopener noreferrer" aria-label="Facebook группа TRIZ Island">
            <span class="material-icons-outlined" aria-hidden="true">groups</span>
          </a>
          <a href="https://www.facebook.com/IrinaDerugina" class="navbar-social-link" target="_blank" rel="noopener noreferrer" aria-label="Facebook профиль Ирины Деругиной">
            <span class="material-icons-outlined" aria-hidden="true">person</span>
          </a>
          <button type="button" class="btn btn-primary-nt ms-1" data-bs-toggle="modal" data-bs-target="#contactModal">
            Записаться / Contact
          </button>
        </div>
      </div>
    </div>
  </nav>
=======
      <div class="collapse navbar-collapse" id="mainNavbar">
        <ul class="navbar-nav ms-auto mb-2 mb-lg-0 me-lg-3">
          <li class="nav-item">
            <a class="nav-link active" href="#hero" data-nav-target="hero">Главная</a>
          </li>
          <li class="nav-item">
            <a class="nav-link" href="#classes" data-nav-target="classes">Классы и расписание</a>
          </li>
          <li class="nav-item">
            <a class="nav-link" href="#mission" data-nav-target="mission">Миссия</a>
          </li>
          <li class="nav-item">
            <a class="nav-link" href="#philosophy" data-nav-target="philosophy">Философия обучения</a>
          </li>
          <li class="nav-item">
            <a class="nav-link" href="#testimonials" data-nav-target="testimonials">Отзывы</a>
          </li>
          <li class="nav-item">
            <a class="nav-link" href="#faq" data-nav-target="faq">FAQ</a>
          </li>
        </ul>
        <div class="d-flex align-items-center gap-2">
          <button type="button" class="btn btn-primary-nt ms-1" data-bs-toggle="modal" data-bs-target="#contactModal">
            Записаться / Contact
          </button>
        </div>
      </div>
      <div class="d-none d-lg-flex align-items-center gap-2 ms-3">
        <a href="https://www.facebook.com/groups/1411313069413512" class="navbar-social-link" target="_blank" rel="noopener noreferrer" aria-label="Facebook группа TRIZ Island">
          <span class="material-icons-outlined" aria-hidden="true">groups</span>
        </a>
        <a href="https://www.facebook.com/IrinaDerugina" class="navbar-social-link" target="_blank" rel="noopener noreferrer" aria-label="Facebook профиль Ирины Деругиной">
          <span class="material-icons-outlined" aria-hidden="true">person</span>
        </a>
      </div>
    </div>
  </nav>
>>>>>>> REPLACE
```
"""

@pytest.fixture
def file_content():
    return """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>TRIZ Island — TRIZ, подготовка к школе, математика и русский язык для детей</title>
  <meta name="description" content="TRIZ Island: классы для детей от 3 лет до 5 класса — TRIZ, подготовка к школе, математика, русский язык, языковые кредиты и тестовая подготовка. Развиваем любопытство, системное мышление и уверенность в учёбе.">
  <meta name="keywords" content="TRIZ Island, TRIZ, NeuroTRIZ, подготовка к школе, математика для детей, русский язык, High School credit, UW STARTALK, развивающие занятия, курсы для детей, креативное мышление">
  <meta name="viewport" content="width=device-width, initial-scale=1">

  <!-- Open Graph -->
  <meta property="og:title" content="TRIZ Island — Пытливый ум для детей">
  <meta property="og:description" content="TRIZ Island: TRIZ и NeuroTRIZ, подготовка к школе, математика, русский язык и языковые кредиты для детей. Развиваем любопытство и системное креативное мышление.">
  <meta property="og:type" content="website">
  <meta property="og:image" content="https://cdn.breba.app/yason/3b6b421bc537498e85a48141804e61ad/assets/TRIZ_hero.jpg">
  <meta property="og:url" content="https://example.com/">

  <!-- Bootstrap CSS -->
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/css/bootstrap.min.css" rel="stylesheet">

  <!-- Google Material Icons (outlined minimalist set) -->
  <link href="https://fonts.googleapis.com/icon?family=Material+Icons+Outlined" rel="stylesheet">

  <style>
    :root {
      --color-bg-main: #ffffff;
      --color-text-primary: #1f2933;
      --color-text-secondary: #4b5563;
      --color-accent: #7ec8e3;
      --color-accent-deep: #2563eb;
      --color-bg-soft: #f3f7fb;
      --color-border: #e5e7eb;
      --color-error: #dc2626;
      --color-footer-bg: #0f172a;
      --color-success-bg: #ecfdf3;
      --color-success-text: #166534;
      --color-error-bg: #fef2f2;
      --color-error-text: #b91c1c;
      --radius-base: 0.5rem;
      --shadow-soft: 0 10px 25px rgba(15, 23, 42, 0.08);
    }

    html {
      scroll-behavior: smooth;
    }

    body {
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background-color: var(--color-bg-main);
      color: var(--color-text-primary);
      line-height: 1.6;
    }

    a {
      color: var(--color-accent-deep);
      text-decoration: none;
    }

    a:hover,
    a:focus {
      text-decoration: underline;
    }

    .section-padding {
      padding-top: 4rem;
      padding-bottom: 4rem;
    }

    @media (min-width: 992px) {
      .section-padding {
        padding-top: 5rem;
        padding-bottom: 5rem;
      }
    }

    /* Navbar */
    .navbar {
      background-color: rgba(255, 255, 255, 0.96);
      border-bottom: 1px solid var(--color-border);
      backdrop-filter: blur(10px);
    }

    .navbar-brand-text {
      font-weight: 700;
      font-size: 1.125rem;
      color: var(--color-text-primary);
    }

    .navbar-nav .nav-link {
      font-weight: 500;
      color: var(--color-text-secondary);
      padding: 0.5rem 0.75rem;
    }

    .navbar-nav .nav-link.active,
    .navbar-nav .nav-link:hover {
      color: var(--color-accent-deep);
    }

    .navbar-nav .nav-link.active {
      border-bottom: 2px solid var(--color-accent-deep);
    }

    .navbar-social-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 2.25rem;
      height: 2.25rem;
      border-radius: 999px;
      border: 1px solid var(--color-border);
      color: var(--color-text-secondary);
      transition: background-color 0.15s ease, color 0.15s ease, border-color 0.15s ease;
    }

    .navbar-social-link .material-icons-outlined {
      font-size: 1.25rem;
    }

    .navbar-social-link:hover {
      background-color: var(--color-bg-soft);
      border-color: var(--color-accent);
      color: var(--color-accent-deep);
      text-decoration: none;
    }

    /* Buttons */
    .btn-primary-nt {
      background-color: var(--color-accent);
      color: #0f172a;
      border-radius: var(--radius-base);
      border: 1px solid var(--color-accent);
      font-weight: 600;
      padding: 0.65rem 1.5rem;
      transition: background-color 0.15s ease, color 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
    }

    .btn-primary-nt:hover,
    .btn-primary-nt:focus {
      background-color: var(--color-accent-deep);
      border-color: var(--color-accent-deep);
      color: #ffffff;
      box-shadow: 0 8px 18px rgba(37, 99, 235, 0.35);
      text-decoration: none;
    }

    .btn-secondary-nt {
      background-color: transparent;
      color: var(--color-accent-deep);
      border-radius: var(--radius-base);
      border: 1px solid var(--color-accent-deep);
      font-weight: 500;
      padding: 0.6rem 1.4rem;
      transition: background-color 0.15s ease, color 0.15s ease, border-color 0.15s ease;
    }

    .btn-secondary-nt:hover,
    .btn-secondary-nt:focus {
      background-color: var(--color-accent-deep);
      color: #ffffff;
      text-decoration: none;
    }

    /* Hero */
    .hero {
      min-height: 100vh;
      display: flex;
      align-items: center;
      padding-top: 5.5rem;
      padding-bottom: 3rem;
    }

    .hero-badge {
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.25rem 0.75rem;
      border-radius: 999px;
      background-color: var(--color-bg-soft);
      color: var(--color-text-secondary);
      font-size: 0.875rem;
      margin-bottom: 1rem;
    }

    .hero-badge .material-icons-outlined {
      font-size: 1.1rem;
      color: var(--color-accent-deep);
    }

    .hero-title {
      font-size: 2rem;
      font-weight: 800;
      margin-bottom: 0.75rem;
    }

    .hero-subtitle {
      font-size: 1.1rem;
      color: var(--color-text-secondary);
      margin-bottom: 1rem;
    }

    .hero-slogan {
      font-weight: 600;
      font-size: 1.1rem;
      margin-bottom: 1rem;
      color: var(--color-accent-deep);
    }

    .hero-text {
      font-size: 1rem;
      color: var(--color-text-secondary);
      margin-bottom: 1.5rem;
    }

    .hero-image-wrapper {
      border-radius: 1rem;
      overflow: hidden;
      box-shadow: var(--shadow-soft);
      background-color: var(--color-bg-soft);
    }

    .hero-image {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }

    .hero-link {
      display: inline-flex;
      align-items: center;
      gap: 0.25rem;
      font-size: 0.95rem;
    }

    .hero-link .material-icons-outlined {
      font-size: 1rem;
    }

    @media (min-width: 992px) {
      .hero-title {
        font-size: 2.5rem;
      }
      .hero-subtitle {
        font-size: 1.15rem;
      }
    }

    /* Sections */
    .section-title {
      font-size: 1.75rem;
      font-weight: 700;
      margin-bottom: 0.5rem;
      text-align: center;
    }

    .section-subtitle {
      font-size: 1.05rem;
      color: var(--color-text-secondary);
      margin-bottom: 2rem;
      text-align: center;
    }

    .bg-soft {
      background-color: var(--color-bg-soft);
    }

    /* Cards */
    .card-nt {
      border-radius: 1rem;
      border: 1px solid var(--color-border);
      background-color: #ffffff;
      padding: 1.5rem;
      height: 100%;
      box-shadow: 0 8px 18px rgba(15, 23, 42, 0.04);
    }

    .icon-circle {
      width: 2.5rem;
      height: 2.5rem;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background-color: var(--color-bg-soft);
      color: var(--color-accent-deep);
      margin-bottom: 0.75rem;
    }

    .icon-circle .material-icons-outlined {
      font-size: 1.4rem;
    }

    .card-nt-title {
      font-weight: 600;
      margin-bottom: 0.4rem;
      font-size: 1.05rem;
    }

    .card-nt-meta {
      font-size: 0.9rem;
      color: var(--color-text-secondary);
      margin-top: 0.5rem;
    }

    /* Mission */
    .highlight-quote {
      border-left: 4px solid var(--color-accent);
      padding-left: 1rem;
      margin-top: 1.5rem;
      margin-bottom: 1rem;
      font-style: italic;
      color: var(--color-text-secondary);
    }

    .mission-tagline {
      font-weight: 500;
      color: var(--color-text-secondary);
      margin-top: 0.5rem;
    }

    /* Philosophy */
    .philosophy-note {
      margin-top: 1.5rem;
      font-size: 0.95rem;
      color: var(--color-text-secondary);
      text-align: center;
    }

    /* Testimonials */
    .testimonial-quote {
      font-style: italic;
      margin-bottom: 0.75rem;
    }

    .testimonial-name {
      font-weight: 600;
      font-size: 0.95rem;
    }

    /* FAQ */
    .accordion-button:not(.collapsed) {
      background-color: var(--color-bg-soft);
      color: var(--color-text-primary);
    }

    /* Modal */
    .modal-header {
      border-bottom: none;
    }

    .modal-footer {
      border-top: none;
    }

    .alert {
      border-radius: 0.75rem;
      padding: 0.75rem 1rem;
      font-size: 0.9rem;
      margin-bottom: 0.75rem;
    }

    .alert-success {
      background-color: var(--color-success-bg);
      color: var(--color-success-text);
      border: 1px solid rgba(22, 101, 52, 0.3);
    }

    .alert-error {
      background-color: var(--color-error-bg);
      color: var(--color-error-text);
      border: 1px solid rgba(185, 28, 28, 0.3);
    }

    /* Footer */
    .footer {
      background-color: var(--color-footer-bg);
      color: #e5e7eb;
      padding-top: 2.5rem;
      padding-bottom: 2rem;
      margin-top: 3rem;
    }

    .footer a {
      color: #cbd5f5;
    }

    .footer a:hover {
      color: #e5e7ff;
      text-decoration: underline;
    }

    .footer-brand {
      font-weight: 700;
      margin-bottom: 0.4rem;
    }

    .footer-nav a {
      font-size: 0.9rem;
      margin-right: 1rem;
    }

    .footer-social {
      display: flex;
      gap: 0.75rem;
    }

    .footer-social-link {
      display: inline-flex;
      align-items: center;
      gap: 0.25rem;
      font-size: 0.9rem;
    }

    .footer-social-link .material-icons-outlined {
      font-size: 1.1rem;
    }
  </style>
</head>
<body>
<header>
  <nav class="navbar navbar-expand-lg fixed-top" aria-label="Основная навигация">
    <div class="container">
      <a class="navbar-brand d-flex align-items-center gap-2" href="#hero">
        <img src="https://cdn.breba.app/templates/images/logo.png" alt="TRIZ Island логотип" width="40" height="40" loading="lazy">
        <span class="navbar-brand-text">TRIZ Island</span>
      </a>
      <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#mainNavbar" aria-controls="mainNavbar" aria-expanded="false" aria-label="Переключить навигацию">
        <span class="navbar-toggler-icon"></span>
      </button>
      <div class="collapse navbar-collapse" id="mainNavbar">
        <ul class="navbar-nav ms-auto mb-2 mb-lg-0 me-lg-3">
          <li class="nav-item">
            <a class="nav-link active" href="#hero" data-nav-target="hero">Главная</a>
          </li>
          <li class="nav-item">
            <a class="nav-link" href="#classes" data-nav-target="classes">Классы и расписание</a>
          </li>
          <li class="nav-item">
            <a class="nav-link" href="#mission" data-nav-target="mission">Миссия</a>
          </li>
          <li class="nav-item">
            <a class="nav-link" href="#philosophy" data-nav-target="philosophy">Философия обучения</a>
          </li>
          <li class="nav-item">
            <a class="nav-link" href="#testimonials" data-nav-target="testimonials">Отзывы</a>
          </li>
          <li class="nav-item">
            <a class="nav-link" href="#faq" data-nav-target="faq">FAQ</a>
          </li>
        </ul>
        <div class="d-flex align-items-center gap-2">
          <a href="https://www.facebook.com/groups/1411313069413512" class="navbar-social-link" target="_blank" rel="noopener noreferrer" aria-label="Facebook группа TRIZ Island">
            <span class="material-icons-outlined" aria-hidden="true">groups</span>
          </a>
          <a href="https://www.facebook.com/IrinaDerugina" class="navbar-social-link" target="_blank" rel="noopener noreferrer" aria-label="Facebook профиль Ирины Деругиной">
            <span class="material-icons-outlined" aria-hidden="true">person</span>
          </a>
          <button type="button" class="btn btn-primary-nt ms-1" data-bs-toggle="modal" data-bs-target="#contactModal">
            Записаться / Contact
          </button>
        </div>
      </div>
    </div>
  </nav>
</header>

<main>
  <!-- Hero -->
  <section id="hero" class="hero" aria-labelledby="hero-title">
    <div class="container">
      <div class="row align-items-center gy-4">
        <div class="col-md-6">
          <div class="hero-badge">
            <span class="material-icons-outlined" aria-hidden="true">psychology</span>
            <span>Создаём обучение для пытливых умов</span>
          </div>
          <h1 id="hero-title" class="hero-title">TRIZ Island — Пытливый ум для детей</h1>
          <p class="hero-subtitle">
            TRIZ Island: классы для детей от 3 лет до 5 класса — TRIZ, подготовка к школе, математика, русский язык и языковые кредиты.
          </p>
          <div class="d-flex flex-wrap align-items-center gap-2">
            <button type="button" class="btn btn-primary-nt" data-bs-toggle="modal" data-bs-target="#contactModal">
              Записаться / Contact
            </button>
            <a href="#classes" class="hero-link">
              <span>Узнать о классах</span>
              <span class="material-icons-outlined" aria-hidden="true">south</span>
            </a>
          </div>
        </div>
        <div class="col-md-6">
          <div class="hero-image-wrapper">
            <img src="https://cdn.breba.app/yason/3b6b421bc537498e85a48141804e61ad/assets/TRIZ_hero.jpg"
                 class="hero-image"
                 alt="Дети, занимающиеся творческими и учебными заданиями в TRIZ Island">
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- Classes & Schedule -->
  <section id="classes" class="section-padding" aria-labelledby="classes-title">
    <div class="container">
      <h2 id="classes-title" class="section-title">Классы и расписание</h2>
      <p class="section-subtitle">От первого вопроса до школьных кредитов</p>
      <div class="row mb-4">
        <div class="col-lg-10 mx-auto">
          <p class="text-center text-muted">
            Программы TRIZ Island соединяют творчество, системное мышление и академическую поддержку.
            Мы подбираем формат и расписание под возраст и интересы ребёнка.
          </p>
        </div>
      </div>
      <div class="row g-4">
        <div class="col-md-6 col-lg-4">
          <article class="card-nt h-100">
            <div class="icon-circle">
              <span class="material-icons-outlined" aria-hidden="true">lightbulb</span>
            </div>
            <h3 class="card-nt-title">TRIZ / NeuroTRIZ Curiosity Lab</h3>
            <p>
              Игровые и проектные занятия по ТРИЗ: учимся находить противоречия, придумывать нестандартные решения и оформлять идеи.
            </p>
            <p class="card-nt-meta">
              <strong>Возраст:</strong> Для детей 6–11 лет (начальная школа)<br>
              <strong>Пример расписания:</strong> 2 раза в неделю, вечерние группы (точное расписание уточнить у преподавателя).
            </p>
          </article>
        </div>
        <div class="col-md-6 col-lg-4">
          <article class="card-nt h-100">
            <div class="icon-circle">
              <span class="material-icons-outlined" aria-hidden="true">school</span>
            </div>
            <h3 class="card-nt-title">Подготовка к школе</h3>
            <p>
              Развитие речи, логики, внимания и базовых учебных навыков для будущих первоклассников.
            </p>
            <p class="card-nt-meta">
              <strong>Возраст:</strong> Для детей 5–7 лет<br>
              <strong>Пример расписания:</strong> Утренние и дневные группы, маленькие классы.
            </p>
          </article>
        </div>
        <div class="col-md-6 col-lg-4">
          <article class="card-nt h-100">
            <div class="icon-circle">
              <span class="material-icons-outlined" aria-hidden="true">functions</span>
            </div>
            <h3 class="card-nt-title">Math Lab / Математика</h3>
            <p>
              Математика как язык задач и идей: от уверенной базы до олимпиадного и углублённого уровня.
            </p>
            <p class="card-nt-meta">
              <strong>Возраст:</strong> 3 класс – 5 класс (по уровням)<br>
              <strong>Пример расписания:</strong> 1–2 раза в неделю, по уровню подготовки.
            </p>
          </article>
        </div>
        <div class="col-md-6 col-lg-4">
          <article class="card-nt h-100">
            <div class="icon-circle">
              <span class="material-icons-outlined" aria-hidden="true">translate</span>
            </div>
            <h3 class="card-nt-title">Русский язык и High School / UW STARTALK кредит</h3>
            <p>
              Русский язык как школьный предмет и как часть идентичности. Подготовка к языковым кредитам и программам типа UW STARTALK.
            </p>
            <p class="card-nt-meta">
              <strong>Возраст:</strong> Средняя и старшая школа (по группам)<br>
              <strong>Пример расписания:</strong> Вечерние онлайн и офлайн группы.
            </p>
          </article>
        </div>
        <div class="col-md-6 col-lg-4">
          <article class="card-nt h-100">
            <div class="icon-circle">
              <span class="material-icons-outlined" aria-hidden="true">task</span>
            </div>
            <h3 class="card-nt-title">Test Preparation / Academic Skills</h3>
            <p>
              Подготовка к тестам, развитие навыков чтения, письма и работы с текстом. Учим не зубрить, а понимать структуру задач.
            </p>
            <p class="card-nt-meta">
              <strong>Возраст:</strong> Старшие классы начальной и средняя школа<br>
              <strong>Пример расписания:</strong> Интенсивы и регулярные занятия, гибкий график.
            </p>
          </article>
        </div>
      </div>
      <div class="row mt-4">
        <div class="col-lg-10 mx-auto">
          <p class="text-center text-muted mb-3">
            Точное расписание и формат (онлайн/офлайн) уточняйте через форму записи — мы подберём группу под возраст и уровень ребёнка.
          </p>
          <div class="d-flex justify-content-center">
            <button type="button" class="btn btn-secondary-nt" data-bs-toggle="modal" data-bs-target="#contactModal">
              Запросить расписание
            </button>
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- Mission -->
  <section id="mission" class="section-padding bg-soft" aria-labelledby="mission-title">
    <div class="container">
      <h2 id="mission-title" class="section-title">Миссия: Взломать код креативности</h2>
      <p class="section-subtitle">TRIZ Island — где нейроны встречаются с алгоритмами изобретений.</p>
      <div class="row g-4">
        <div class="col-md-4">
          <article class="card-nt h-100">
            <div class="icon-circle">
              <span class="material-icons-outlined" aria-hidden="true">psychology</span>
            </div>
            <p>Мы — сообщество, где встречаются пытливый ум и системный подход.</p>
          </article>
        </div>
        <div class="col-md-4">
          <article class="card-nt h-100">
            <div class="icon-circle">
              <span class="material-icons-outlined" aria-hidden="true">hub</span>
            </div>
            <p>Наш дом — точка пересечения нейронауки, искусственного интеллекта и теории решения изобретательских задач (ТРИЗ).</p>
          </article>
        </div>
        <div class="col-md-4">
          <article class="card-nt h-100">
            <div class="icon-circle">
              <span class="material-icons-outlined" aria-hidden="true">bolt</span>
            </div>
            <p>Наша миссия — взломать код креативности. Мы изучаем, как работает curiosity-двигатель в человеческом мозге, чтобы создать новые инструменты для изобретателей.</p>
          </article>
        </div>
      </div>
      <div class="row mt-4">
        <div class="col-lg-10 mx-auto">
          <div class="highlight-quote">
            “Что, если бы у любопытства была инструкция? А у гениальных идей — общая формула?”
          </div>
          <p class="mission-tagline">
            ПытливУм — инструкция к любопытству ещё не написана. Пишем её вместе с детьми и родителями.
          </p>
        </div>
      </div>
    </div>
  </section>

  <!-- Teaching Philosophy -->
  <section id="philosophy" class="section-padding" aria-labelledby="philosophy-title">
    <div class="container">
      <h2 id="philosophy-title" class="section-title">Философия обучения</h2>
      <p class="section-subtitle">Curiosity + TRIZ + Neuro = инструменты для жизни</p>
      <div class="row g-4">
        <div class="col-md-6 col-lg-3">
          <article class="card-nt h-100">
            <div class="icon-circle">
              <span class="material-icons-outlined" aria-hidden="true">question_mark</span>
            </div>
            <h3 class="card-nt-title">Curiosity First / Сначала любопытство</h3>
            <p>
              Мы превращаем вопросы детей в топливо для обучения. Не даём готовых ответов, а вместе строим маршрут поиска.
            </p>
          </article>
        </div>
        <div class="col-md-6 col-lg-3">
          <article class="card-nt h-100">
            <div class="icon-circle">
              <span class="material-icons-outlined" aria-hidden="true">build</span>
            </div>
            <h3 class="card-nt-title">TRIZ as a Toolkit / ТРИЗ как набор инструментов</h3>
            <p>
              Дети учатся видеть противоречия, искать ресурсы и применять алгоритмы изобретений к задачам из реальной жизни и учебы.
            </p>
          </article>
        </div>
        <div class="col-md-6 col-lg-3">
          <article class="card-nt h-100">
            <div class="icon-circle">
              <span class="material-icons-outlined" aria-hidden="true">memory</span>
            </div>
            <h3 class="card-nt-title">Neuro + AI в помощь учителю</h3>
            <p>
              Мы опираемся на идеи из нейронауки и используем нейросети как партнёров: для визуализаций, идей и игр с информацией.
            </p>
          </article>
        </div>
        <div class="col-md-6 col-lg-3">
          <article class="card-nt h-100">
            <div class="icon-circle">
              <span class="material-icons-outlined" aria-hidden="true">all_inclusive</span>
            </div>
            <h3 class="card-nt-title">От вопроса до решения / Full Cycle</h3>
            <p>
              Цех Любопытства Curios Lab — это производство идей полного цикла: от сырого вопроса до готового решения и презентации.
            </p>
          </article>
        </div>
      </div>
      <p class="philosophy-note">
        Noetrix, РазбериZ, Mindvention, CogniTRIZ, Synaptic Solve — это разные грани одного подхода:
        обучать думать системно и творчески.
      </p>
    </div>
  </section>

  <!-- Testimonials -->
  <section id="testimonials" class="section-padding bg-soft" aria-labelledby="testimonials-title">
    <div class="container">
      <h2 id="testimonials-title" class="section-title">Отзывы родителей и учеников</h2>
      <p class="section-subtitle">Первые результаты — в любопытных глазах и уверенности детей</p>
      <div class="row g-4">
        <div class="col-md-4">
          <article class="card-nt h-100">
            <p class="testimonial-quote">
              “Ребёнок начал сам придумывать задачи и спрашивать ‘а что если…’. Школа перестала быть просто местом, куда надо ходить — ему стало интересно думать.”
            </p>
            <p class="testimonial-name">Анна, мама ученика 3 класса</p>
          </article>
        </div>
        <div class="col-md-4">
          <article class="card-nt h-100">
            <p class="testimonial-quote">
              “Подготовка к школе была не про рабочие тетради, а про развитие мышления. Дочь стала увереннее, научилась не бояться сложных заданий.”
            </p>
            <p class="testimonial-name">Мария, мама будущей первоклассницы</p>
          </article>
        </div>
        <div class="col-md-4">
          <article class="card-nt h-100">
            <p class="testimonial-quote">
              “С TRIZ и NeuroTRIZ сын по-другому смотрит на математику и проекты. Это не репетиторство, а среда для настоящих маленьких изобретателей.”
            </p>
            <p class="testimonial-name">Игорь, папа ученика 5 класса</p>
          </article>
        </div>
      </div>
    </div>
  </section>

  <!-- FAQ -->
  <section id="faq" class="section-padding" aria-labelledby="faq-title">
    <div class="container">
      <h2 id="faq-title" class="section-title">FAQ — Часто задаваемые вопросы</h2>
      <p class="section-subtitle">Ответы на популярные вопросы о TRIZ Island</p>

      <div class="accordion" id="faqAccordion">
        <div class="accordion-item">
          <h3 class="accordion-header" id="faq-heading-1">
            <button class="accordion-button" type="button" data-bs-toggle="collapse" data-bs-target="#faq-collapse-1" aria-expanded="true" aria-controls="faq-collapse-1">
              Каким детям подойдут ваши классы?
            </button>
          </h3>
          <div id="faq-collapse-1" class="accordion-collapse collapse show" aria-labelledby="faq-heading-1" data-bs-parent="#faqAccordion">
            <div class="accordion-body">
              Наши программы рассчитаны на детей от 3 лет до 5 класса и старше для языковых и кредитных курсов.
              Подойдут как «очень любопытным» детям, так и тем, кому нужна поддержка в учебе, уверенность в задачах и тестах.
            </div>
          </div>
        </div>

        <div class="accordion-item">
          <h3 class="accordion-header" id="faq-heading-2">
            <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#faq-collapse-2" aria-expanded="false" aria-controls="faq-collapse-2">
              В чём отличие ваших TRIZ/NeuroTRIZ занятий от обычных кружков?
            </button>
          </h3>
          <div id="faq-collapse-2" class="accordion-collapse collapse" aria-labelledby="faq-heading-2" data-bs-parent="#faqAccordion">
            <div class="accordion-body">
              Мы не даём готовых шаблонов. Дети учатся видеть противоречия, задавать нестандартные вопросы, строить решения и презентовать их.
              Мы соединяем ТРИЗ, элементы нейронауки и современные инструменты (включая нейросети), чтобы тренировать мышление.
            </div>
          </div>
        </div>

        <div class="accordion-item">
          <h3 class="accordion-header" id="faq-heading-3">
            <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#faq-collapse-3" aria-expanded="false" aria-controls="faq-collapse-3">
              Как проходит подготовка к школе?
            </button>
          </h3>
          <div id="faq-collapse-3" class="accordion-collapse collapse" aria-labelledby="faq-heading-3" data-bs-parent="#faqAccordion">
            <div class="accordion-body">
              Подготовка к школе включает развитие речи, логики, внимания, мелкой моторики, базовых математических представлений и учебных привычек.
              Мы много играем, обсуждаем и учим ребёнка не бояться ошибок.
            </div>
          </div>
        </div>

        <div class="accordion-item">
          <h3 class="accordion-header" id="faq-heading-4">
            <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#faq-collapse-4" aria-expanded="false" aria-controls="faq-collapse-4">
              Что такое Russian language High School credit и UW STARTALK language credit?
            </button>
          </h3>
          <div id="faq-collapse-4" class="accordion-collapse collapse" aria-labelledby="faq-heading-4" data-bs-parent="#faqAccordion">
            <div class="accordion-body">
              Это программы и экзамены, которые позволяют засчитать русский язык как предмет и получить официальные школьные кредиты.
              Мы помогаем подготовиться к таким программам, укрепить язык и выстроить системную базу.
            </div>
          </div>
        </div>

        <div class="accordion-item">
          <h3 class="accordion-header" id="faq-heading-5">
            <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#faq-collapse-5" aria-expanded="false" aria-controls="faq-collapse-5">
              Как записаться и узнать точное расписание?
            </button>
          </h3>
          <div id="faq-collapse-5" class="accordion-collapse collapse" aria-labelledby="faq-heading-5" data-bs-parent="#faqAccordion">
            <div class="accordion-body">
              Самый быстрый способ — оставить запрос через форму на сайте (кнопка «Записаться / Contact»).
              Напишите возраст ребёнка, интересующие направления (TRIZ, подготовка к школе, математика, русский, кредиты), и мы свяжемся с вами
              с подробным расписанием и вариантами групп.
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</main>

<!-- Footer -->
<footer class="footer" aria-label="Подвал сайта">
  <div class="container">
    <div class="row gy-4 align-items-start">
      <div class="col-md-5">
        <div class="d-flex align-items-center gap-2 mb-2">
          <img src="https://cdn.breba.app/templates/images/logo.png" alt="TRIZ Island логотип" width="36" height="36" loading="lazy">
          <div class="footer-brand">TRIZ Island — Пытливый ум</div>
        </div>
        <p class="mb-2">
          Сообщество любопытных умов. Дети, родители, идеи и изобретения.
        </p>
        <p class="small mb-0">
          Мы взламываем код креативности и гениальных идей. Пишем инструкцию к любопытству вместе.
        </p>
      </div>
      <div class="col-md-3">
        <nav class="footer-nav" aria-label="Навигация в подвале">
          <a href="#hero">Главная</a>
          <a href="#classes">Классы</a>
          <a href="#mission">Миссия</a>
          <a href="#faq">FAQ</a>
          <a href="#hero" data-bs-toggle="modal" data-bs-target="#contactModal">Записаться</a>
        </nav>
      </div>
      <div class="col-md-4">
        <div class="mb-2 fw-semibold">Мы в соцсетях</div>
        <div class="footer-social mb-2">
          <a href="https://www.facebook.com/groups/1411313069413512" class="footer-social-link" target="_blank" rel="noopener noreferrer">
            <span class="material-icons-outlined" aria-hidden="true">groups</span>
            <span>Facebook группа</span>
          </a>
        </div>
        <div class="footer-social">
          <a href="https://www.facebook.com/IrinaDerugina" class="footer-social-link" target="_blank" rel="noopener noreferrer">
            <span class="material-icons-outlined" aria-hidden="true">person</span>
            <span>Профиль Ирины Деругиной</span>
          </a>
        </div>
      </div>
    </div>
    <hr class="mt-4 mb-3" style="border-color: rgba(148, 163, 184, 0.4);">
    <div class="d-flex flex-column flex-md-row justify-content-between align-items-center gap-2">
      <div class="small">
        © <span id="current-year"></span> TRIZ Island. Все права защищены.
      </div>
      <div class="small text-muted">
        TRIZ Island — Пытливый ум для детей от 3 лет до 5 класса и старше.
      </div>
    </div>
  </div>
</footer>

<!-- Contact Modal -->
<div class="modal fade" id="contactModal" tabindex="-1" aria-labelledby="contactModalLabel" aria-hidden="true">
  <div class="modal-dialog modal-dialog-centered">
    <div class="modal-content">
      <div class="modal-header">
        <h2 class="modal-title fs-5" id="contactModalLabel">Записаться на класс / Задать вопрос</h2>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Закрыть"></button>
      </div>
      <div class="modal-body">
        <p class="text-muted small mb-3">
          Оставьте свои контакты и кратко опишите возраст ребёнка и интересующие направления.
          Мы свяжемся с вами, чтобы подобрать формат и расписание.
        </p>
        <div id="form-success" class="alert alert-success d-none" role="status">
          Спасибо! Мы получили ваше сообщение и свяжемся с вами в ближайшее время.
        </div>
        <div id="form-error" class="alert alert-error d-none" role="alert">
          Произошла ошибка при отправке. Пожалуйста, попробуйте ещё раз позже.
        </div>
        <form id="contact-form" novalidate>
          <div class="mb-3">
            <label for="name" class="form-label">Имя</label>
            <input type="text" class="form-control" id="name" name="name" required>
            <div class="invalid-feedback">Пожалуйста, укажите ваше имя.</div>
          </div>
          <div class="mb-3">
            <label for="email" class="form-label">Email</label>
            <input type="email" class="form-control" id="email" name="email" required>
            <div class="invalid-feedback">Пожалуйста, введите корректный email.</div>
          </div>
          <div class="mb-3">
            <label for="message" class="form-label">Сообщение</label>
            <textarea class="form-control" id="message" name="message" rows="4" required placeholder="Возраст ребёнка, интересующие классы (TRIZ, подготовка к школе, математика, русский, кредиты) и удобное время."></textarea>
            <div class="invalid-feedback">Пожалуйста, напишите короткое сообщение.</div>
          </div>

          <!-- Staticforms.xyz hidden fields -->
          <input type="hidden" name="subject" value="New TRIZ Island Inquiry">
          <input type="hidden" name="replyTo" value="@">
          <input type="hidden" name="accessKey" value="YOUR_STATICFORMS_API_KEY">

          <div class="modal-footer px-0">
            <button type="button" class="btn btn-link text-muted me-auto" data-bs-dismiss="modal">
              Отмена
            </button>
            <button type="submit" class="btn btn-primary-nt">
              Отправить
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</div>

<!-- Bootstrap JS Bundle -->
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>

<script>
  // Set current year in footer
  document.addEventListener('DOMContentLoaded', function () {
    var yearSpan = document.getElementById('current-year');
    if (yearSpan) {
      yearSpan.textContent = new Date().getFullYear();
    }
  });

  // Smooth scrolling and active nav link handling
  document.addEventListener('DOMContentLoaded', function () {
    var navLinks = document.querySelectorAll('.navbar-nav .nav-link[data-nav-target]');
    var sections = [];

    navLinks.forEach(function (link) {
      var targetId = link.getAttribute('data-nav-target');
      var section = document.getElementById(targetId);
      if (section) {
        sections.push({ id: targetId, element: section });
      }

      link.addEventListener('click', function (event) {
        var href = link.getAttribute('href');
        if (href && href.startsWith('#')) {
          event.preventDefault();
          var target = document.querySelector(href);
          if (target) {
            var offset = document.querySelector('.navbar').offsetHeight + 16;
            var top = target.getBoundingClientRect().top + window.pageYOffset - offset;
            window.scrollTo({ top: top, behavior: 'smooth' });
          }
          var navbarCollapse = document.getElementById('mainNavbar');
          if (navbarCollapse && navbarCollapse.classList.contains('show')) {
            var bsCollapse = bootstrap.Collapse.getInstance(navbarCollapse);
            if (bsCollapse) {
              bsCollapse.hide();
            }
          }
        }
      });
    });

    function onScroll() {
      var scrollPos = window.pageYOffset || document.documentElement.scrollTop;
      var navbarHeight = document.querySelector('.navbar').offsetHeight + 32;
      var currentId = null;

      sections.forEach(function (section) {
        var rect = section.element.getBoundingClientRect();
        var offsetTop = rect.top + window.pageYOffset - navbarHeight;
        if (scrollPos >= offsetTop) {
          currentId = section.id;
        }
      });

      if (!currentId) {
        currentId = 'hero';
      }

      navLinks.forEach(function (link) {
        if (link.getAttribute('data-nav-target') === currentId) {
          link.classList.add('active');
        } else {
          link.classList.remove('active');
        }
      });
    }

    window.addEventListener('scroll', onScroll);
    onScroll();
  });

  // Contact form submission with Staticforms.xyz via AJAX
  document.addEventListener('DOMContentLoaded', function () {
    var form = document.getElementById('contact-form');
    if (!form) {
      return;
    }

    var successAlert = document.getElementById('form-success');
    var errorAlert = document.getElementById('form-error');

    form.addEventListener('submit', function (event) {
      event.preventDefault();
      successAlert.classList.add('d-none');
      errorAlert.classList.add('d-none');

      if (!form.checkValidity()) {
        event.stopPropagation();
        form.classList.add('was-validated');
        return;
      }

      var formData = new FormData(form);

      fetch('https://api.staticforms.xyz/submit', {
        method: 'POST',
        body: formData
      })
        .then(function (response) {
          if (!response.ok) {
            throw new Error('Network response was not ok');
          }
          return response.json();
        })
        .then(function (data) {
          if (data && data.success) {
            successAlert.classList.remove('d-none');
            form.reset();
            form.classList.remove('was-validated');
          } else {
            errorAlert.classList.remove('d-none');
          }
        })
        .catch(function () {
          errorAlert.classList.remove('d-none');
        });
    });

    // Reset messages when modal is closed
    var contactModal = document.getElementById('contactModal');
    if (contactModal) {
      contactModal.addEventListener('hidden.bs.modal', function () {
        successAlert.classList.add('d-none');
        errorAlert.classList.add('d-none');
        form.classList.remove('was-validated');
      });
    }
  });
</script>
</body>
</html>
    """

def test_apply_search_replace_many(search_replace_block, file_content):
    filestore = from_raw_strings({"index.html": file_content})
    result = apply_search_replace_many(filestore, search_replace_block)
    assert result == ["index.html"]
    assert filestore.read_text("index.html") != file_content


def test_apply_search_replace_many_file_mismatch(search_replace_block, file_content):
    filestore = from_raw_strings({"index2.html": file_content})
    try:
        apply_search_replace_many(filestore, search_replace_block)
    except ApplyEditsError as e:
        assert "File not found: index.html" in str(e)
    else:
        assert False, "Must raise error"


def test_apply_search_replace_many_empty_file(search_replace_block, file_content):
    filestore = from_raw_strings({"index.html": ""})
    try:
        apply_search_replace_many(filestore, search_replace_block)
    except ApplyEditsError as e:
        assert "Content is empty" in str(e)
    else:
        assert False, "Must raise error"