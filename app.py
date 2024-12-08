import hashlib
import os
from datetime import datetime  # representing and manipulating date and time
from datetime import (  # representing the difference between two dates or times; ( Getting the time difference )
    timedelta,
)
from os.path import dirname, join

from bson.objectid import ObjectId
from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from pymongo import MongoClient
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)

dotenv_path = join(dirname(__file__), ".env")
load_dotenv(dotenv_path)

MONGODB_URI = os.environ.get("MONGODB_URI")
DB_NAME = os.environ.get("DB_NAME")
SECRET_KEY = os.environ.get("SECRET_KEY")

app.secret_key = SECRET_KEY

conn = MongoClient(MONGODB_URI)
db = conn[DB_NAME]

# Middleware untuk memastikan login
def login_required(f):
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", msg="Silakan login untuk melanjutkan."))
        return f(*args, **kwargs)

    wrapper.__name__ = f.__name__
    return wrapper


# Middleware untuk memastikan hanya admin yang bisa mengakses
def admin_only(f):
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            return redirect(url_for("home"))
        return f(*args, **kwargs)

    wrapper.__name__ = f.__name__
    return wrapper


# ROUTE HALAMAN UTAMA
@app.route("/", methods=["GET"])
@login_required
def home():
    user_id = session.get("user_id")
    movies = db.movies.find({})

    return render_template("user/home.html", movies=movies, user_id=user_id)


from bson import ObjectId  # Untuk konversi ID MongoDB


@app.route("/movies/detail", methods=["GET", "POST"])
@login_required
def movie_detail():
    user_id = session.get("user_id")
    movie_id = request.args.get("id")

    # Mendapatkan detail film
    movie = db.movies.find_one({"_id": ObjectId(movie_id)})

    # Menambahkan komentar jika ada
    if request.method == "POST":
        comment = request.form.get("comment")
        if comment:
            db.movies.update_one(
                {"_id": ObjectId(movie_id)},
                {"$push": {"comments": {"user_id": user_id, "comment": comment, "date": datetime.now()}}}
            )
            return redirect(url_for('movie_detail', id=movie_id))  # Reload page

    # Mendapatkan komentar untuk film ini
    comments = movie.get("comments", [])

    return render_template("user/movie_detail.html", movies=movie, user_id=user_id, comments=comments)


# ROUTE HALAMAN LOGIN
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username_receive = request.form["username_give"]
        password_receive = request.form["password_give"]
        password_hash = hashlib.sha256(password_receive.encode("utf-8")).hexdigest()

        user = db.user_login.find_one(
            {"username": username_receive, "password": password_hash}
        )

        if user:
            session["user_id"] = user["username"]
            session["role"] = user.get("role", "user")  # Default role adalah 'user'
            return redirect(url_for("home"))
        else:
            msg = "ID pengguna atau sandi salah."
            return render_template("user/login.html", msg=msg)

    msg = request.args.get("msg")
    return render_template("user/login.html", msg=msg)


# ROUTE HALAMAN SIGN UP
@app.route("/sign_up", methods=["GET"])
def sign_up_page():
    return render_template("user/sign_up.html")


# ROUTE UNTUK LOGOUT
@app.route("/logout", methods=["GET"])
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


# ROUTE CEK DUPLICATE ID PENDAFTARAN
@app.route("/check_username/<username>", methods=["GET"])
def check_username(username):
    # Mengecek apakah username sudah terdaftar di MongoDB
    user = db.user_login.find_one({"username": username})
    if user:
        return jsonify({"exists": True})
    else:
        return jsonify({"exists": False})


# ROUTE UNTUK MENYIMPAN DATA PENDAFTARAN USER
@app.route("/sign_up/save", methods=["POST"])
def sign_up():
    username_receive = request.form["username_give"]
    password_receive = request.form["password_give"]
    name_receive = request.form["name_give"]

    # Cek apakah username sudah ada di database
    existing_user = db.user_login.find_one({"username": username_receive})
    if existing_user:
        # Jika username sudah ada, kembalikan pesan error
        return redirect(url_for("sign_up_page", msg="Username sudah terdaftar."))

    # Enkripsi password
    password_hash = hashlib.sha256(password_receive.encode("utf-8")).hexdigest()

    # Simpan data pendaftaran user
    doc = {
        "username": username_receive,
        "password": password_hash,
        "name": name_receive,
        "role": "user",  # Default role adalah 'user'
    }
    db.user_login.insert_one(doc)

    # Redirect ke halaman login dengan parameter success untuk menampilkan modal
    return redirect(url_for("login", msg="Pendaftaran berhasil, Silakan login."))


# ROUTE ADMIN: HALAMAN ADMIN
@app.route("/admin", methods=["GET"])
@login_required
@admin_only
def admin_dashboard():
    user_count = db.user_login.count_documents({})

    # Mengambil data jumlah film
    movie_count = db.movies.count_documents({})
    
    # Hitung jumlah komentar dari semua film
    comment_count_pipeline = [
        {"$unwind": {"path": "$comments", "preserveNullAndEmptyArrays": True}},  # Membongkar array comments
        {"$group": {"_id": None, "total_comments": {"$sum": 1}}},  # Menghitung jumlah total
    ]
    comment_count_result = list(db.movies.aggregate(comment_count_pipeline))
    total_comments = comment_count_result[0]["total_comments"] if comment_count_result else 0

    # Mengambil data jumlah review
    review_count = db.reviews.count_documents({})
    users = list(db.user_login.find({}))
    return render_template(
        "admin/dashboard.html",
        users=users,
        user_count=user_count,
        movie_count=movie_count,
        total_comments=total_comments,
    )


# ROUTE ADMIN: HALAMAN KELOLA PENGGUNA
@app.route("/admin/users", methods=["GET"])
@login_required
@admin_only
def manage_users():
    # Ambil data pengguna dari database
    users = list(db.user_login.find({}))
    return render_template("admin/manage_users.html", users=users)


# ROUTE ADMIN: HALAMAN EDIT PENGGUNA (untuk mempermudah edit)
@app.route("/admin/users/edit/<user_id>", methods=["GET", "POST"])
@login_required
@admin_only
def edit_user(user_id):
    user = db.user_login.find_one({"_id": ObjectId(user_id)})

    if request.method == "POST":
        # Proses form untuk mengedit data pengguna
        username_receive = request.form["username_give"]
        name_receive = request.form["name_give"]
        role_receive = request.form["role_give"]

        # Update data pengguna
        db.user_login.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "username": username_receive,
                    "name": name_receive,
                    "role": role_receive,
                }
            },
        )
        return redirect(url_for("manage_users"))

    return render_template("admin/edit_user.html", user=user)


# ROUTE ADMIN: HALAMAN HAPUS PENGGUNA (akan diakses melalui POST di halaman kelola pengguna)
@app.route("/admin/users/delete/<user_id>", methods=["POST"])
@login_required
@admin_only
def delete_user(user_id):
    db.user_login.delete_one({"_id": ObjectId(user_id)})
    return redirect(url_for("manage_users"))


# ROUTE ADMIN: HALAMAN KELOLA FILM
@app.route("/admin/movies", methods=["GET"])
@login_required
@admin_only
def manage_movies():
    # Mengambil data film dari database
    movies = list(db.movies.find({}))
    return render_template("admin/manage_movies.html", movies=movies)


# ROUTE ADMIN: HALAMAN TAMBAH FILM
@app.route("/admin/movies/add", methods=["GET", "POST"])
@login_required
@admin_only
def add_movie():
    if request.method == "POST":
        title = request.form["title"]
        year = request.form["year"]
        director = request.form["director"]
        cast = request.form["cast"]
        category = request.form["category"]
        description = request.form["description"]

        new_doc = {
            "title": title,
            "year": year,
            "director": director,
            "cast": cast,
            "category": category,
            "description": description,
        }

        # Menangani upload gambar
        photo = request.files["cover_image"]  # Mengambil file gambar dari request
        if photo:
            filename = secure_filename(photo.filename)
            extension = filename.split(".")[-1]  # Mengambil ekstensi file
            # Membuat path file dengan mengganti spasi pada judul dengan '_'
            file_path = f"cover_film/{title.replace(' ', '_')}.{extension}"
            photo.save("./static/" + file_path)
            new_doc["cover_image"] = file_path
            new_doc["photo"] = filename

        else:
            file_path = None  # Jika tidak ada gambar atau gambar tidak valid

        # Menyimpan data film di MongoDB
        db.movies.insert_one(new_doc)

        flash("Film berhasil ditambahkan!", "success")
        return redirect(url_for("manage_movies"))

    return render_template("admin/manage_movies.html")


# ROUTE ADMIN: HALAMAN EDIT FILM
@app.route("/admin/movies/edit/<movie_id>", methods=["GET", "POST"])
@login_required
@admin_only
def edit_movie(movie_id):
    movie = db.movies.find_one({"_id": ObjectId(movie_id)})

    if request.method == "POST":
        # Ambil data film dari form
        title = request.form["title"]
        category = request.form["category"]
        year = request.form["year"]
        director = request.form["director"]
        cast = request.form["cast"]
        description = request.form["description"]

        new_doc = {
            "title": title,
            "year": year,
            "director": director,
            "cast": cast,
            "category": category,
            "description": description,
        }

        # Memeriksa apakah ada gambar yang diupload
        cover_image = request.files.get("cover_image")
        if cover_image:
            filename = secure_filename(cover_image.filename)
            extension = filename.split(".")[-1]  # Mengambil ekstensi file
            file_path = f"cover_film/{title.replace(' ', '_')}.{extension}"
            cover_image.save("./static/" + file_path)
            new_doc["cover_image"] = file_path
            new_doc["photo"] = filename
        # Update data film
        db.movies.update_one(
            {"_id": ObjectId(movie_id)},
            {"$set": new_doc},  # let user know how to do update
        )
        return redirect(url_for("manage_movies"))

    return render_template("admin/manage_movies.html", movie=movie)


# ROUTE ADMIN: HALAMAN HAPUS FILM
@app.route("/admin/movies/delete/<movie_id>", methods=["POST"])
@login_required
@admin_only
def delete_movie(movie_id):
    db.movies.delete_one({"_id": ObjectId(movie_id)})
    return redirect(url_for("manage_movies"))


if __name__ == "__main__":
    app.run("0.0.0.0", port=5000, debug=True)
