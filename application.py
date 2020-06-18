import os

from flask import Flask, session, render_template, request, redirect, jsonify, flash, url_for
from flask_session import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from helpers import login_required
from datetime import timedelta
import requests

app = Flask(__name__)
app.secret_key = 'hello'
#app.permanent_session_lifetime = timedelta(minutes=5) ##############
# Check for environment variable
if not os.getenv("DATABASE_URL"):
    raise RuntimeError("DATABASE_URL is not set")

# Configure session to use filesystem
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Set up database
engine = create_engine(os.getenv("DATABASE_URL"))
db = scoped_session(sessionmaker(bind=engine))


@app.route("/")
def index():
    #results = db.execute("SELECT DISTINCT isbn, title, author, year FROM books JOIN reviews ON reviews.book_id = books.id ORDER BY reviews.id DESC LIMIT 81").fetchall()
    #results = db.execute("SELECT DISTINCT isbn, title, author, year FROM (SELECT isbn, title, author, year FROM books JOIN reviews ON reviews.book_id = books.id ORDER BY reviews.id DESC) AS FOO LIMIT 81").fetchall()
    results = db.execute("SELECT isbn, title, author, year FROM books JOIN reviews ON reviews.book_id = books.id ORDER BY reviews.id DESC").fetchall()
    bumped = []
    seen = []
    for result in results:
        if result.isbn not in seen:
            bumped.append(result)
            seen.append(result.isbn)
    return render_template("index.html", results = bumped)

@app.route("/search", methods=["GET"])
@login_required
def search():
    #Get form information
    keyword = str(request.args.get("keyword"))

    keywords = keyword.split()
    myquery = []
    d = {}
    for word in keywords:
        command = f"( UPPER(title) LIKE UPPER(:{word}) OR \
        isbn LIKE :{word} OR \
        UPPER(author) LIKE UPPER(:{word}) )"
        myquery.append(command)
        d[word] = '%' + word + '%'
    commands = " AND ".join(myquery)

    # query = '%' + keyword + '%'

    # #List results
    # results = db.execute("SELECT * FROM books WHERE\
    #     UPPER(title) LIKE UPPER(:query) OR \
    #     isbn LIKE :query OR \
    #     UPPER(author) LIKE UPPER(:query)", {"query": query}).fetchall()

    results = db.execute("SELECT * FROM books WHERE " + commands, d).fetchall()
    numres = str(len(results))
    return render_template("search.html", results = results, keyword = keyword, numres = numres)


@app.route("/lucky", methods=["GET"])
@login_required
def lucky():
    randomBook = db.execute("SELECT isbn FROM books ORDER BY RANDOM() LIMIT 1").fetchone()
    randomBook_isbn = str(randomBook.isbn)
    flash('Abra kadabra!')
    return redirect("/book/" + randomBook_isbn)

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":
        #Collect all form data
        username = request.form.get("username")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")
        terms = request.form.get("terms")

        #Username was submitted
        if not username:
            flash('You must provide a username', 'warning')
            return redirect("/register")

        #Only letters and numbers
        if not username.isalnum():
            flash("Username can only contain letters and numbers", "warning")
            return redirect("/register")

        #Username length fits
        if not (3 <= len(username) <= 12):
            flash("Username lenght must be between 3 and 12", "warning")
            return redirect("/register")

        #Username is not taken
        if db.execute("SELECT * FROM users WHERE username = :username", {"username": username}).rowcount:
            flash("This username is not available", "warning")
            return redirect("/register")

        #Password was submitted
        if not password:
            flash("You must provide a password", "warning")
            return redirect("/register")

        #Password was confirmed
        if password != confirmation:
            flash("Password does not match", "warning")
            return redirect("/register")

        #Password length fits
        if not (3 <= len(password) <= 12):
            flash("Password lenght must be between 3 and 12", "warning")
            return redirect("/register")

        #Terms were accepted
        if not terms:
            flash("You must agree with our terms and conditions", "warning")
            return redirect("/register")

        #Create user in DB and save
        db.execute("INSERT INTO users (username, password) VALUES (:username, :password)", {"username": username, "password": password})
        db.commit()

        #Redirect to login
        flash('Welcome aboard!', 'info')
        return redirect("/login")

    else:
        if "user_id" in session:
            return redirect("/")
        return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":
        #Collect all form data
        username = request.form.get("username")
        password = request.form.get("password")

        #Username and password were submitted
        if not username:
            flash("You didn't provide a username", "warning")
            return redirect("/login")
        if not password:
            flash("You didn't provide a password", "warning")
            return redirect("/login")

        #Username exists in DB and matches password
        user = db.execute("SELECT * FROM users WHERE username = :username", {"username": username}).fetchone()
        if (not user) or user.password != password:
            flash("Password or username are incorrect", "warning")
            return redirect("/login")

        #Create new session for logged in user
        session["user_id"] = user.id
        session["user_name"] = user.username

        #Redirect to home page
        return redirect("/")

    else:
        if "user_id" in session:
            return redirect("/")
        return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/book/<isbn>", methods=["GET", "POST"])
@login_required
def book(isbn):

    #Book exists in our DB
    book = db.execute("SELECT * FROM books WHERE isbn = :isbn", {"isbn": isbn}).fetchone()
    if not book:
        return render_template("error.html", message = "This book does not exist")
    

    if request.method == "POST":

        #Collect form data (rating & comment)
        try:
            rating = int(request.form.get("rating"))
        except:
            return render_template("error.html", message = "Invalid rating")
        comment = request.form.get("comment")
        onlineUser = session["user_id"]

        if not rating:
            flash("Must submit a rating", "warning")
            return redirect("/book/" + isbn)
        if not comment:
            flash("Must submit a comment", "warning")
            return redirect("/book/" + isbn)

        #Review was already submitted, delete old one
        if db.execute("SELECT * FROM reviews WHERE user_id = :user_id AND book_id = :book_id", {"user_id": onlineUser, "book_id": book.id}).rowcount:
            db.execute("DELETE FROM reviews WHERE user_id = :user_id AND book_id = :book_id", {"user_id": onlineUser, "book_id": book.id})

        #Insert new review on book
        db.execute("INSERT INTO reviews (user_id, book_id, comment, rating) VALUES \
                    (:user_id, :book_id, :comment, :rating)",
                    {"user_id": onlineUser, 
                    "book_id": book.id, 
                    "comment": comment, 
                    "rating": rating})
        db.commit()
        flash('Review submitted!', 'info')
        return redirect("/book/" + isbn)

    #Fetch comments form database for display
    reviews = db.execute("SELECT comment, rating, username \
                          FROM reviews JOIN users ON users.id = reviews.user_id \
                          WHERE book_id = :book_id ORDER BY reviews.id DESC", {"book_id": book.id}).fetchall()

    #Fetch user last review
    userrev = db.execute("SELECT rating FROM reviews WHERE user_id = :user_id AND book_id = :book_id", {"user_id": session["user_id"], "book_id": book.id}).fetchone()

    #GOODREADS REVIEW
    key = os.getenv("GOODREADS_KEY")
    res = requests.get("https://www.goodreads.com/book/review_counts.json", params={"key": key, "isbns": isbn})
    if res.status_code != 200:
        raise Exception("ERROR: API request unsuccessful.")
    data = res.json()
    goodstat = data['books'][0]

    #BOOKWORM REVIEW
    row = db.execute("SELECT title, author, year, isbn, \
                    COUNT(reviews.id) as review_count, \
                    AVG(reviews.rating) as average_score \
                    FROM books \
                    INNER JOIN reviews \
                    ON books.id = reviews.book_id \
                    WHERE isbn = :isbn \
                    GROUP BY title, author, year, isbn",
                    {"isbn": isbn})

    # Error checking
    if row.rowcount != 1:
        result = {"average_score": "n/a", "review_count": 0}
        return render_template("book.html", book = book, reviews = reviews, goodstat = goodstat, userrev = userrev, bwstat = result)

    # Fetch result from RowProxy    
    tmp = row.fetchone()

    # Convert to dict
    result = dict(tmp.items())

    # Round Avg Score to 2 decimal. This returns a string which does not meet the requirement.
    # https://floating-point-gui.de/languages/python/
    result['average_score'] = float('%.2f'%(result['average_score']))

    return render_template("book.html", book = book, reviews = reviews, goodstat = goodstat, userrev = userrev, bwstat = result)


@app.route("/user/<username>", methods=["GET"])
@login_required
def user(username):
    #User exists
    target = db.execute("SELECT * FROM users WHERE username = :username", {"username": username}).fetchone()
    if not target:
        return render_template("error.html", message = "User doesn't Exists!")

    #Fetch books where user commented
    onlineUser = int(target.id)
    userReviews = db.execute("SELECT isbn, title, rating FROM books JOIN reviews ON reviews.book_id = books.id WHERE user_id = :onlineUser ORDER BY reviews.id DESC", {"onlineUser": onlineUser}).fetchall()
    return render_template("user.html", userReviews = userReviews, username = target.username)


@app.route("/api/<isbn>", methods=['GET'])
def api_call(isbn):
    row = db.execute("SELECT title, author, year, isbn, \
                    COUNT(reviews.id) as review_count, \
                    AVG(reviews.rating) as average_score \
                    FROM books \
                    INNER JOIN reviews \
                    ON books.id = reviews.book_id \
                    WHERE isbn = :isbn \
                    GROUP BY title, author, year, isbn",
                    {"isbn": isbn})

    # Error checking
    if row.rowcount != 1:
        return jsonify({"Error": "Invalid book ISBN"}), 422

    # Fetch result from RowProxy    
    tmp = row.fetchone()

    # Convert to dict
    result = dict(tmp.items())

    # Round Avg Score to 2 decimal. This returns a string which does not meet the requirement.
    # https://floating-point-gui.de/languages/python/
    result['average_score'] = float('%.2f'%(result['average_score']))

    return jsonify(result)

@app.errorhandler(404)
def page_not_found(e):
    # note that we set the 404 status explicitly
    return render_template('error.html', message = "Error 404, page not found!"), 404