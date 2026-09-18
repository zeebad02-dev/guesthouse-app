import csv
import io
from flask import Flask, jsonify, request, render_template, Response
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///guesthouse.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ----------------- Database Models -----------------
class Room(db.Model):
    __tablename__ = 'rooms'
    id = db.Column(db.Integer, primary_key=True)
    room_number = db.Column(db.String(10), unique=True, nullable=False)
    room_type = db.Column(db.String(50), nullable=False)
    price_per_night = db.Column(db.Float, nullable=False)
    is_occupied = db.Column(db.Boolean, default=False)

class Item(db.Model):
    __tablename__ = 'items'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    total_stock = db.Column(db.Integer, default=0)
    unit_price = db.Column(db.Float, nullable=False)

class RoomInventory(db.Model):
    __tablename__ = 'room_inventory'
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('items.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)

# ----------------- Routes -----------------

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/rooms', methods=['GET'])
def get_rooms():
    rooms = Room.query.all()
    results = []
    for room in rooms:
        allocations = RoomInventory.query.filter_by(room_id=room.id).all()
        room_items = []
        for alloc in allocations:
            item = db.session.get(Item, alloc.item_id)
            if item:
                room_items.append({
                    "item_id": item.id,
                    "name": item.name,
                    "quantity": alloc.quantity,
                    "unit_price": item.unit_price
                })
        results.append({
            "id": room.id,
            "room_number": room.room_number,
            "room_type": room.room_type,
            "price_per_night": room.price_per_night,
            "is_occupied": room.is_occupied,
            "inventory": room_items
        })
    return jsonify(results), 200

# NEW: Create a new room
@app.route('/api/rooms', methods=['POST'])
def add_room():
    data = request.get_json()
    if not data or 'room_number' not in data or 'room_type' not in data or 'price_per_night' not in data:
        return jsonify({"error": "Missing required fields"}), 400
    
    if Room.query.filter_by(room_number=data['room_number']).first():
        return jsonify({"error": "Room number already exists"}), 400

    new_room = Room(
        room_number=data['room_number'],
        room_type=data['room_type'],
        price_per_night=float(data['price_per_night']),
        is_occupied=False
    )
    db.session.add(new_room)
    db.session.commit()
    return jsonify({"message": "Room created successfully"}), 201

# NEW: Create a new inventory item
@app.route('/api/items', methods=['POST'])
def add_item():
    data = request.get_json()
    if not data or 'name' not in data or 'total_stock' not in data or 'unit_price' not in data:
        return jsonify({"error": "Missing required fields"}), 400

    if Item.query.filter_by(name=data['name']).first():
        return jsonify({"error": "Item already exists"}), 400

    new_item = Item(
        name=data['name'],
        total_stock=int(data['total_stock']),
        unit_price=float(data['unit_price'])
    )
    db.session.add(new_item)
    db.session.commit()
    return jsonify({"message": "Item created successfully"}), 201

@app.route('/api/rooms/<int:room_id>/toggle-occupancy', methods=['POST'])
def toggle_occupancy(room_id):
    room = db.session.get(Room, room_id)
    if not room:
        return jsonify({"error": "Room not found"}), 404
    room.is_occupied = not room.is_occupied
    db.session.commit()
    return jsonify({"message": "Occupancy updated", "is_occupied": room.is_occupied}), 200

@app.route('/api/rooms/<int:room_id>/inventory', methods=['POST'])
def update_room_inventory(room_id):
    room = db.session.get(Room, room_id)
    if not room:
        return jsonify({"error": "Room not found"}), 404
    data = request.get_json()
    item_id = data['item_id']
    quantity = int(data['quantity'])

    allocation = RoomInventory.query.filter_by(room_id=room.id, item_id=item_id).first()
    if allocation:
        if quantity <= 0:
            db.session.delete(allocation)
        else:
            allocation.quantity = quantity
    elif quantity > 0:
        allocation = RoomInventory(room_id=room.id, item_id=item_id, quantity=quantity)
        db.session.add(allocation)

    db.session.commit()
    return jsonify({"message": "Inventory updated"}), 200

@app.route('/api/inventory/summary', methods=['GET'])
def get_inventory_summary():
    items = Item.query.all()
    summary = []
    for item in items:
        allocated = db.session.query(db.func.sum(RoomInventory.quantity)).filter_by(item_id=item.id).scalar() or 0
        available_in_storage = item.total_stock - allocated
        summary.append({
            "item_id": item.id,
            "name": item.name,
            "total_stock": item.total_stock,
            "allocated_in_rooms": allocated,
            "in_storage": available_in_storage,
            "low_stock_warning": available_in_storage < 5
        })
    return jsonify(summary), 200

# NEW: Export CSV Report Route
@app.route('/api/reports/export', methods=['GET'])
def export_csv_report():
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Section 1: Rooms Report
    writer.writerow(["--- ROOM STATUS REPORT ---"])
    writer.writerow(["Room Number", "Room Type", "Price/Night", "Status"])
    rooms = Room.query.all()
    for r in rooms:
        writer.writerow([r.room_number, r.room_type, r.price_per_night, "Occupied" if r.is_occupied else "Vacant"])
    
    writer.writerow([])
    
    # Section 2: Inventory Summary Report
    writer.writerow(["--- INVENTORY SUMMARY REPORT ---"])
    writer.writerow(["Item Name", "Total Stock", "Allocated to Rooms", "In Storage", "Status"])
    items = Item.query.all()
    for item in items:
        allocated = db.session.query(db.func.sum(RoomInventory.quantity)).filter_by(item_id=item.id).scalar() or 0
        in_storage = item.total_stock - allocated
        status = "LOW STOCK" if in_storage < 5 else "OK"
        writer.writerow([item.name, item.total_stock, allocated, in_storage, status])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=guesthouse_report.csv"}
    )

if __name__ == '__main__':
    app.run(debug=True, port=5000)