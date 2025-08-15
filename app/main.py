from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import Course, Lesson, User, UserLessonProgress

app = FastAPI(title="Python E-Learning Dashboard")

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)

    with Session(bind=engine) as db:
        # Seed demo user
        user = db.execute(select(User).where(User.id == 1)).scalar_one_or_none()
        if user is None:
            user = User(id=1, name="Demo Learner")
            db.add(user)
            db.commit()

        # Seed demo content if empty
        has_any_courses = db.execute(select(func.count(Course.id))).scalar_one() > 0
        if not has_any_courses:
            python_basics = Course(
                title="Python Basics",
                description="Learn Python fundamentals: variables, control flow, functions, and more.",
            )
            python_advanced = Course(
                title="Advanced Python",
                description="Dive deeper: iterators, generators, context managers, and async.",
            )
            db.add_all([python_basics, python_advanced])
            db.flush()

            basics_lessons = [
                Lesson(course_id=python_basics.id, title="Getting Started", content="Intro to Python and setup.", order_index=1, duration_minutes=8),
                Lesson(course_id=python_basics.id, title="Variables & Types", content="Numbers, strings, lists, dicts.", order_index=2, duration_minutes=12),
                Lesson(course_id=python_basics.id, title="Control Flow", content="if/elif/else, loops.", order_index=3, duration_minutes=15),
                Lesson(course_id=python_basics.id, title="Functions", content="Defining and calling functions.", order_index=4, duration_minutes=18),
            ]

            advanced_lessons = [
                Lesson(course_id=python_advanced.id, title="Iterators & Generators", content="yield and iterator protocol.", order_index=1, duration_minutes=14),
                Lesson(course_id=python_advanced.id, title="Decorators", content="Function decoration patterns.", order_index=2, duration_minutes=16),
                Lesson(course_id=python_advanced.id, title="Context Managers", content="with statements and contextlib.", order_index=3, duration_minutes=10),
                Lesson(course_id=python_advanced.id, title="Async IO", content="Coroutines and asyncio.", order_index=4, duration_minutes=20),
            ]

            db.add_all(basics_lessons + advanced_lessons)
            db.flush()

            # Initialize progress rows for demo user
            for lesson in basics_lessons + advanced_lessons:
                db.add(
                    UserLessonProgress(
                        user_id=user.id,
                        lesson_id=lesson.id,
                        completed=False,
                        completed_at=None,
                    )
                )

            db.commit()


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    courses: List[Course] = db.execute(select(Course)).scalars().all()

    # Build progress summary per course for user 1
    progress_by_course: Dict[int, Tuple[int, int]] = {}
    for course in courses:
        total_lessons = db.execute(
            select(func.count(Lesson.id)).where(Lesson.course_id == course.id)
        ).scalar_one()

        completed_count = db.execute(
            select(func.count(UserLessonProgress.id))
            .join(Lesson, Lesson.id == UserLessonProgress.lesson_id)
            .where(
                UserLessonProgress.user_id == 1,
                Lesson.course_id == course.id,
                UserLessonProgress.completed.is_(True),
            )
        ).scalar_one()

        progress_by_course[course.id] = (completed_count, total_lessons)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "courses": courses,
            "progress_by_course": progress_by_course,
        },
    )


@app.get("/course/{course_id}", response_class=HTMLResponse)
def course_detail(course_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    course = db.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")

    # Fetch lessons with user progress
    lessons = db.execute(
        select(Lesson).where(Lesson.course_id == course_id).order_by(Lesson.order_index)
    ).scalars().all()

    progress_rows = db.execute(
        select(UserLessonProgress).where(
            UserLessonProgress.user_id == 1,
            UserLessonProgress.lesson_id.in_([lesson.id for lesson in lessons] or [0]),
        )
    ).scalars().all()
    progress_map: Dict[int, UserLessonProgress] = {p.lesson_id: p for p in progress_rows}

    return templates.TemplateResponse(
        "course_detail.html",
        {
            "request": request,
            "course": course,
            "lessons": lessons,
            "progress_map": progress_map,
        },
    )


@app.post("/lesson/{lesson_id}/toggle")
def toggle_lesson_completion(lesson_id: int, request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    lesson = db.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="Lesson not found")

    progress = db.execute(
        select(UserLessonProgress).where(
            UserLessonProgress.user_id == 1,
            UserLessonProgress.lesson_id == lesson_id,
        )
    ).scalar_one_or_none()

    if progress is None:
        progress = UserLessonProgress(user_id=1, lesson_id=lesson_id, completed=True, completed_at=datetime.utcnow())
        db.add(progress)
    else:
        progress.completed = not progress.completed
        progress.completed_at = datetime.utcnow() if progress.completed else None

    db.commit()

    referer = request.headers.get("referer", "/")
    return RedirectResponse(url=referer, status_code=303)