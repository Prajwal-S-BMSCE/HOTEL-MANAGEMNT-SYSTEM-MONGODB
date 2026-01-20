from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
import random
import string
from pymongo import MongoClient
from datetime import datetime
from bson import ObjectId  # Needed to query by user_id

# --- IMPORTS for ALL FEATURES ---
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from email_validator import validate_email, EmailNotValidError
import razorpay
from flask_mail import Mail, Message

# --- 1. APP INITIALIZATION & CONFIG ---
app = Flask(__name__)
# Your random string
app.config['SECRET_KEY'] = 'f4a8f1b3e9d6c7a8b0c5d4e3f2a1b9c8d+=--++@#$%^0e7f6a5b4c3d2e1f0a9b8c7d6e5f4a3' 

# Razorpay Config
app.config['RAZORPAY_KEY_ID'] = 'rzp_test_Rg01tqD38BFkoS'
app.config['RAZORPAY_KEY_SECRET'] = 'sloamBFanRtyZh7mxzvnuDq0'

# Flask-Mail Config
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'prajwalsprajju2005@gmail.com'
app.config['MAIL_PASSWORD'] = 'fsdp mizb tkav mapf' # Your 16-character App Password

# --- 2. EXTENSION INITIALIZATION ---
mail = Mail(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
razorpay_client = razorpay.Client(
    auth=(app.config['RAZORPAY_KEY_ID'], app.config['RAZORPAY_KEY_SECRET'])
)

# Flask-Login setup
login_manager.login_view = 'login' 
login_manager.login_message_category = 'info'

# --- 3. MONGODB CONNECTION & COLLECTIONS ---
client = MongoClient('mongodb://localhost:27017/')
db = client['hotel']

# All collections for the app
bookings_collection = db['bookings']
room_service_collection = db['room_service']
payment_collection = db['payment']
room_info_collection = db['room_info'] # We will use this in Step 6
rooms_collection = db['rooms'] 
users_collection = db['users']
menu_items_collection = db['menu_items'] # For Step 5

# --- 4. ONE-TIME DATABASE SETUP (Rooms & Menu) ---
try:
    if rooms_collection.count_documents({}) == 0:
        rooms_collection.insert_many([
            { "room_number": "101", "room_type": "Deluxe Room", "price": 12000, "image_url": "https://img.homejournal.com/202008/5f2775523eb16.jpeg" },
            { "room_number": "102", "room_type": "Deluxe Room", "price": 12000, "image_url": "https://img.homejournal.com/202008/5f2775523eb16.jpeg" },
            { "room_number": "201", "room_type": "Suite", "price": 17500, "image_url": "https://www.theleela.com/prod/content/assets/styles/tl_1920_768/public/tl-mumbai-premier-suite-02-1920x768.jpg" },
            { "room_number": "202", "room_type": "Suite", "price": 17500, "image_url": "https://www.theleela.com/prod/content/assets/styles/tl_1920_768/public/tl-mumbai-premier-suite-02-1920x768.jpg" },
            { "room_number": "301", "room_type": "Presidential Suite", "price": 30000, "image_url": "https://cache.marriott.com/marriottassets/marriott/LASBR/lasbr-suite-0117-hor-clsc.jpg" }
        ])
        print("Room inventory created successfully.")
    else:
        print("Room inventory already exists.")
        
    if menu_items_collection.count_documents({}) == 0:
        menu_items_collection.insert_many([
            { "name": "Chicken Biryani", "price": 450, "category": "Main Course", "image_url": "https://via.placeholder.com/150/FF5733/FFFFFF?text=Biryani" },
            { "name": "Paneer Butter Masala", "price": 380, "category": "Main Course", "image_url": "https://via.placeholder.com/150/FFC300/FFFFFF?text=Paneer" },
            { "name": "Garlic Naan", "price": 80, "category": "Breads", "image_url": "https://via.placeholder.com/150/DAF7A6/FFFFFF?text=Naan" },
            { "name": "Masala Dosa", "price": 220, "category": "Breakfast", "image_url": "https://via.placeholder.com/150/33FF57/FFFFFF?text=Dosa" },
            { "name": "Chocolate Lava Cake", "price": 250, "category": "Desserts", "image_url": "https://via.placeholder.com/150/581845/FFFFFF?text=Cake" }
        ])
        print("Menu created successfully.")
    else:
        print("Menu already exists.")
except Exception as e:
    print(f"Error setting up initial data: {e}")

# --- 5. USER MODEL & LOADER ---
class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data['_id'])
        self.email = user_data['email']
        self.name = user_data['name']
        self.password_hash = user_data['password_hash']

    @staticmethod
    def get(user_id):
        user_data = users_collection.find_one({'_id': ObjectId(user_id)})
        if user_data:
            return User(user_data)
        return None

@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

# --- 6. HELPER FUNCTIONS ---
def generate_unique_id():
    """Generates a unique booking ID."""
    return "ANCASA" + ''.join(random.choices(string.digits, k=4))

def send_email(to, subject, template, **kwargs):
    """Sends an asynchronous email."""
    try:
        msg = Message(
            subject,
            sender=('Hotel AnCasa', app.config['MAIL_USERNAME']),
            recipients=[to]
        )
        msg.html = render_template(template, **kwargs)
        mail.send(msg)
        print(f"Email sent to {to}")
    except Exception as e:
        print(f"Error sending email: {e}")

def get_bill_details_for_booking(booking):
    """Calculates bill details for a given booking document."""
    check_in_date = booking.get("checkin")
    check_out_date = booking.get("checkout")
    
    # --- FIX for bad data ---
    if not check_in_date or not check_out_date:
        return {"room_charges": 0, "restaurant_charges": 0, "total_amount": 0}

    duration = (check_out_date - check_in_date).days
    if duration == 0: duration = 1
    
    room_base_price = booking.get("room_price", 0)
    room_charges = room_base_price * duration
    
    booking_id_str = str(booking.get("_id"))
    pipeline = [
        { "$match": { "booking_id": ObjectId(booking_id_str) } }, 
        { "$group": { 
            "_id": None, 
            "total": { "$sum": { "$multiply": [ "$Price", "$Quantity" ] } }
        }}
    ]
    agg_result = list(room_service_collection.aggregate(pipeline))
    restaurant_charges = agg_result[0]['total'] if agg_result else 0
    
    return {
        "room_charges": room_charges,
        "restaurant_charges": restaurant_charges,
        "total_amount": room_charges + restaurant_charges
    }

# --- 7. AUTHENTICATION ROUTES ---

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('home')) 

    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        try:
            validate_email(email)
        except EmailNotValidError:
            flash('Invalid email address.', 'danger')
            return redirect(url_for('signup'))

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('signup'))
            
        existing_user = users_collection.find_one({'email': email.lower()})
        if existing_user:
            flash('Email address already in use.', 'danger')
            return redirect(url_for('signup'))

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user_doc = {
            'name': name,
            'email': email.lower(),
            'password_hash': hashed_password,
            'created_at': datetime.now()
        }
        users_collection.insert_one(new_user_doc)
        
        # --- Send Welcome Email ---
        send_email(
            to=email.lower(),
            subject='Welcome to Hotel AnCasa!',
            template='email/welcome.html',
            name=name
        )
        
        flash('Account created successfully! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('signup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user_data = users_collection.find_one({'email': email.lower()})
        
        if user_data and bcrypt.check_password_hash(user_data['password_hash'], password):
            user = User(user_data)
            login_user(user, remember=True)
            flash('Logged in successfully.', 'success')
            
            next_page = request.args.get('next') 
            return redirect(next_page or url_for('home'))
        else:
            flash('Login unsuccessful. Please check email and password.', 'danger')
            
    return render_template('login.html')


@app.route('/logout')
@login_required 
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('home'))

# --- 8. MAIN PAGE ROUTES ---

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/book_room.html', methods=['GET'])
@login_required 
def book_room():
    return render_template('book_room.html')


@app.route('/submit_booking', methods=['POST'])
@login_required 
def submit_booking():
    user_id = current_user.id
    name = current_user.name
    email = current_user.email
    phone = request.form.get('phone') 

    check_in_str = request.form.get('checkin')
    check_out_str = request.form.get('checkout')
    room_number = request.form.get('room_number') 
    
    room_details = rooms_collection.find_one({"room_number": room_number})
    if not room_details:
        return "Error: Selected room not found.", 400
        
    room_type = room_details['room_type']
    room_price = room_details['price'] 
    
    customer_id = generate_unique_id()
    
    checkin_date = datetime.strptime(check_in_str, '%Y-%m-%d')
    checkout_date = datetime.strptime(check_out_str, '%Y-%m-%d')
    
    try:
        new_booking_doc = {
            "user_id": ObjectId(user_id), 
            "customer_id": customer_id, 
            "name": name,
            "phone": phone,
            "email": email,
            "checkin": checkin_date,
            "checkout": checkout_date,
            "guests": request.form.get('guests'),
            "room_number": room_number,
            "room_type": room_type,
            "room_price": room_price,
            "preferences": request.form.get('preferences', ''),
            "booking_date": datetime.now()
        }
        
        bookings_collection.insert_one(new_booking_doc)
        
        # --- Send Booking Confirmation Email ---
        send_email(
            to=email,
            subject='Your Hotel AnCasa Booking is Confirmed!',
            template='email/booking_confirmation.html',
            name=name,
            booking_id=customer_id,
            room_type=room_type,
            room_number=room_number,
            checkin_date=checkin_date.strftime('%d %b, %Y'),
            checkout_date=checkout_date.strftime('%d %b, %Y')
        )

        return redirect(url_for('booking_success', customer_id=customer_id, room_number=room_number))

    except Exception as e:
        print(f"Error submitting booking: {e}")
        return "An error occurred while booking.", 500

@app.route('/booking_success.html')
@login_required 
def booking_success():
    customer_id = request.args.get('customer_id')
    room_number = request.args.get('room_number')
    return render_template('booking_success.html', customer_id=customer_id, room_number=room_number)


@app.route('/room.html', methods=['GET'])
def room():
    try:
        # --- This query finds the unique room types ---
        # It groups by 'room_type' and takes the price/image from the first room it finds.
        pipeline = [
            {
                "$group": {
                    "_id": "$room_type",
                    "price": { "$first": "$price" },
                    "image_url": { "$first": "$image_url" },
                    # You can add a description to your DB and fetch it here
                    # "description": { "$first": "$description" } 
                }
            },
            {
                "$project": {
                    "room_type": "$_id",
                    "price": 1,
                    "image_url": 1,
                    "_id": 0 # Hide the ugly '_id'
                }
            },
            {
                "$sort": { "price": 1 } # Sort by price, cheapest first
            }
        ]
        
        room_types = list(rooms_collection.aggregate(pipeline))
        
        # We also need to add descriptions, as they aren't in the DB yet.
        # (Ideally, you would add this to your rooms_collection)
        descriptions = {
            "Deluxe Room": "Enjoy the ultimate comfort in our Deluxe Room featuring a king-size bed and a private balcony with a stunning view.",
            "Suite": "Indulge in the luxurious Suite Room with a separate living area, premium furnishings, and exclusive access to our rooftop lounge.",
            "Presidential Suite": "Experience unmatched luxury in our Presidential Suite with a private pool and panoramic views of the city.",
            "Single Room": "Perfect for the solo traveler, our Single Room offers comfort and convenience in a compact, elegant space.",
            "Double Room": "Ideal for couples or friends, our Double Room provides ample space and two plush beds.",
            "Penthouse": "The pinnacle of luxury. Our Penthouse features multiple rooms, a private terrace, and unparalleled service."
        }
        
        for room in room_types:
            room['description'] = descriptions.get(room['room_type'], "No description available.")
            
        return render_template('room.html', rooms=room_types)

    except Exception as e:
        print(f"Error fetching room types: {e}")
        # If DB fails, still show the page
        return render_template('room.html', rooms=[])


@app.route('/services.html', methods=['GET'])
@login_required 
def services():
    active_bookings = bookings_collection.find({
        "user_id": ObjectId(current_user.id),
        "checkout": {"$gt": datetime.now()} 
    }).sort("checkin", 1)
    
    return render_template('services.html', bookings=list(active_bookings))

@app.route('/order_successful.html')
@login_required
def order_successful():
    return render_template('order_successful.html')

@app.route('/my_account')
@login_required
def my_account():
    try:
        # Get the current time to see what's "upcoming"
        now = datetime.now()
        
        # 1. Find upcoming bookings for this user
        upcoming_bookings = list(bookings_collection.find({
            "user_id": ObjectId(current_user.id),
            "checkout": {"$gt": now} # Checkout date is in the future
        }).sort("checkin", 1)) # Sort by check-in date
        
        # 2. Find past bookings for this user
        past_bookings = list(bookings_collection.find({
            "user_id": ObjectId(current_user.id),
            "checkout": {"$lte": now} # Checkout date is in the past
        }).sort("checkin", -1)) # Sort by most recent
        
        return render_template(
            'my_account.html', 
            upcoming_bookings=upcoming_bookings, 
            past_bookings=past_bookings
        )
    except Exception as e:
        print(f"Error fetching account details: {e}")
        flash("Could not load your account details. Please try again.", "danger")
        return redirect(url_for('home'))

@app.route('/payment.html', methods=['GET'])
@login_required 
def payment():
    user_bookings = bookings_collection.find({
        "user_id": ObjectId(current_user.id)
    }).sort("checkin", -1)
    
    return render_template('payment.html', bookings=list(user_bookings))


@app.route('/payment_success')
@login_required
def payment_success():
    # Fetch the most recent payment for this user to show on the receipt
    latest_payment = payment_collection.find_one(
        {"user_id": ObjectId(current_user.id)},
        sort=[("payment_date", -1)] # Sort by newest first
    )
    
    if not latest_payment:
        return redirect(url_for('home')) # Should not happen if they just paid

    # Prepare data for the template
    payment_info = {
        "name": latest_payment.get("name"),
        "payment_id": latest_payment.get("payment_id"),
        "date": latest_payment.get("payment_date").strftime('%d %b, %Y %I:%M %p'),
        "room_type": latest_payment.get("room_type"),
        "room_charges": latest_payment.get("room_charges"),
        "restaurant_charges": latest_payment.get("restaurant_charges"),
        "total_amount": latest_payment.get("total_amount")
    }

    return render_template('payment_success.html', payment_info=payment_info)


# --- 9. API ROUTES (The "Brains") ---

@app.route('/api/available_rooms', methods=['GET'])
@login_required 
def get_available_rooms():
    try:
        checkin_str = request.args.get('checkin')
        checkout_str = request.args.get('checkout')
        if not checkin_str or not checkout_str:
            return jsonify({"error": "Check-in and check-out dates are required."}), 400
        checkin_date = datetime.strptime(checkin_str, '%Y-%m-%d')
        checkout_date = datetime.strptime(checkout_str, '%Y-%m-%d')
        if checkout_date <= checkin_date:
            return jsonify({"error": "Check-out date must be after check-in date."}), 400
        
        booked_rooms_query = bookings_collection.find({
            "checkin": {"$lt": checkout_date},
            "checkout": {"$gt": checkin_date}
        })
        booked_room_numbers = [booking['room_number'] for booking in booked_rooms_query]
        available_rooms_query = rooms_collection.find({
            "room_number": {"$nin": booked_room_numbers}
        }).sort("price", 1)
        
        available_rooms = []
        for room in available_rooms_query:
            available_rooms.append({
                "room_number": room['room_number'],
                "room_type": room['room_type'],
                "price": room['price']
            })
        return jsonify(available_rooms)
    except Exception as e:
        print(f"Error checking availability: {e}")
        return jsonify({"error": "An server error occurred."}), 500


@app.route('/api/get_menu')
@login_required
def get_menu():
    try:
        # This is an "aggregation pipeline"
        # It tells MongoDB to group the items for us
        pipeline = [
            { "$sort": { "name": 1 } }, # Sort items alphabetically
            {
                "$group": {
                    "_id": "$category", # Group by the "category" field
                    "items": { 
                        "$push": { # Add each item into an "items" array
                            "_id": "$_id",
                            "name": "$name",
                            "price": "$price",
                            "image_url": "$image_url"
                        }
                    }
                }
            },
            { "$sort": { "_id": 1 } } # Sort the categories (e.g., Breakfast, Desserts)
        ]
        
        grouped_menu = list(menu_items_collection.aggregate(pipeline))
        
        # Convert all ObjectIds to strings
        for category in grouped_menu:
            for item in category['items']:
                item['_id'] = str(item['_id'])
                
        # The result looks like:
        # [ { "_id": "Breakfast", "items": [...] }, { "_id": "Main Course", "items": [...] } ]
        
        return jsonify(grouped_menu)
    except Exception as e:
        print(f"Error fetching menu: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/add_service', methods=['POST'])
@login_required
def add_service():
    try:
        data = request.json
        booking_id_str = data.get('booking_id')
        cart = data.get('cart')
        
        if not booking_id_str or not cart:
            return jsonify({"error": "Missing booking ID or cart."}), 400

        booking = bookings_collection.find_one({
            "_id": ObjectId(booking_id_str),
            "user_id": ObjectId(current_user.id)
        })
        if not booking:
            return jsonify({"error": "Booking not found or access denied."}), 403

        items_to_insert = []
        for item in cart:
            menu_item = menu_items_collection.find_one({"_id": ObjectId(item['_id'])})
            if not menu_item:
                print(f"Warning: Item {item['_id']} not found in menu. Skipping.")
                continue

            new_service_doc = {
                "booking_id": ObjectId(booking_id_str),
                "customer_id": booking['customer_id'],
                "user_id": ObjectId(current_user.id),
                "FoodItem": menu_item['name'],
                "Quantity": item['quantity'],
                "Price": menu_item['price'],
                "order_date": datetime.now()
            }
            items_to_insert.append(new_service_doc)
        
        if not items_to_insert:
            return jsonify({"error": "No valid items to order."}), 400
            
        room_service_collection.insert_many(items_to_insert)
        
        return jsonify({"success": True, "message": "Order placed successfully!"})
    
    except Exception as e:
        print(f"Error in add_service: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/get_customer_details')
@login_required 
def get_customer_details():
    booking_id_str = request.args.get('booking_id') 
    try:
        booking = bookings_collection.find_one({
            "_id": ObjectId(booking_id_str),
            "user_id": ObjectId(current_user.id)
        })
    except:
        return jsonify({"error": "Invalid Booking ID format"}), 400

    if booking:
        bill_details = get_bill_details_for_booking(booking)
        
        if bill_details['total_amount'] == 0 and not bill_details['room_charges'] and not bill_details['restaurant_charges']:
             if not booking.get("checkin") or not booking.get("checkout"):
                print(f"Error: Booking {booking.get('_id')} has missing dates.")
                return jsonify({"error": "Booking data is incomplete. Cannot calculate bill."}), 500

        customer_details = {
            "name": booking.get("name"),
            "phone": booking.get("phone"),
            "email": booking.get("email"),
            "check_in": booking.get("checkin").strftime('%Y-%m-%d') if booking.get("checkin") else "N/A",
            "check_out": booking.get("checkout").strftime('%Y-%m-%d') if booking.get("checkout") else "N/A",
            "room_type": booking.get("room_type"),
            "room_charges": bill_details['room_charges'],
            "restaurant_charges": bill_details['restaurant_charges'],
            "total_amount": bill_details['total_amount'],
            "payment_status": booking.get("payment_status", "Pending")
        }
        return jsonify(customer_details)
    else:
        return jsonify({"error": "Booking not found or access denied"}), 404


@app.route('/api/create_payment_order', methods=['POST'])
@login_required
def create_payment_order():
    try:
        data = request.json
        booking_id_str = data.get('booking_id')
        
        if not booking_id_str:
            return jsonify({"error": "Missing booking ID"}), 400

        booking = bookings_collection.find_one({
            "_id": ObjectId(booking_id_str),
            "user_id": ObjectId(current_user.id)
        })
        if not booking:
            return jsonify({"error": "Booking not found or access denied"}), 404
            
        bill_details = get_bill_details_for_booking(booking)
        amount_in_paise = int(bill_details['total_amount'] * 100)
        
        if amount_in_paise <= 0:
            return jsonify({"error": "Total amount must be greater than zero."}), 400

        order_data = {
            'amount': amount_in_paise,
            'currency': 'INR',
            'receipt': f'booking_{booking_id_str}',
            'notes': {
                'booking_id': booking_id_str,
                'user_id': current_user.id
            }
        }
        
        order = razorpay_client.order.create(data=order_data)
        
        bookings_collection.update_one(
            { "_id": ObjectId(booking_id_str) },
            { "$set": { "razorpay_order_id": order['id'] } }
        )
        
        return jsonify({
            'order_id': order['id'],
            'key_id': app.config['RAZORPAY_KEY_ID'],
            'amount': order['amount'],
            'currency': order['currency'],
            'name': booking['name'],
            'email': booking['email'],
            'phone': booking['phone']
        })

    except Exception as e:
        print(f"Error creating Razorpay order: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/verify_payment', methods=['POST'])
@login_required
def verify_payment():
    try:
        data = request.json
        booking_id_str = data.get('booking_id')
        razorpay_payment_id = data.get('razorpay_payment_id')
        razorpay_order_id = data.get('razorpay_order_id')
        razorpay_signature = data.get('razorpay_signature')
        
        booking = bookings_collection.find_one({
            "_id": ObjectId(booking_id_str),
            "user_id": ObjectId(current_user.id)
        })
        
        if not booking or booking.get('razorpay_order_id') != razorpay_order_id:
            return jsonify({"error": "Booking not found or order ID mismatch"}), 400

        params_dict = {
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature
        }
        
        razorpay_client.utility.verify_payment_signature(params_dict)
        
        bookings_collection.update_one(
            { "_id": ObjectId(booking_id_str) },
            { "$set": { 
                "payment_status": "Paid", 
                "payment_id": razorpay_payment_id 
            }}
        )
        
        bill_details = get_bill_details_for_booking(booking) 
        
        new_payment_doc = {
            "user_id": ObjectId(current_user.id),
            "booking_id": ObjectId(booking_id_str),
            "payment_id": razorpay_payment_id,
            "order_id": razorpay_order_id,
            "name": booking.get("name"),
            "phone": booking.get("phone"),
            "email": booking.get("email"),
            "check_in": booking.get("checkin").strftime('%Y-%m-%d'),
            "check_out": booking.get("checkout").strftime('%Y-%m-%d'),
            "room_type": booking.get("room_type"),
            "room_charges": bill_details['room_charges'],
            "restaurant_charges": bill_details['restaurant_charges'],
            "total_amount": bill_details['total_amount'],
            "payment_date": datetime.now()
        }
        payment_collection.insert_one(new_payment_doc)
        
        # --- Send Payment Receipt Email ---
        send_email(
            to=booking.get("email"),
            subject='Payment Received - Hotel AnCasa',
            template='email/booking_confirmation.html', # Re-using template
            name=booking.get("name"),
            booking_id=booking.get("customer_id"),
            room_type=booking.get("room_type"),
            room_number=booking.get("room_number"),
            checkin_date=booking.get("checkin").strftime('%d %b, %Y'),
            checkout_date=booking.get("checkout").strftime('%d %b, %Y')
        )
        
        return jsonify({"success": True, "message": "Payment verified successfully."})

    except razorpay.errors.SignatureVerificationError:
        return jsonify({"error": "Payment signature verification failed"}), 400
    except Exception as e:
        print(f"Error verifying payment: {e}")
        return jsonify({"error": str(e)}), 500

# --- 10. APP RUNNER ---
if __name__ == '__main__':
    app.run(debug=True)