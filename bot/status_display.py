"""
Real-time status display for bot activity
"""
import datetime


class StatusDisplay:
    """Real-time status display for bot activity"""
    def __init__(self, symbol: str, usd_amount: float):
        self.symbol = symbol
        self.usd_amount = usd_amount
        self.current_price = None
        self.current_order = None
        self.recent_actions = []
        self.max_actions = 10
        self.start_time = None

    def start(self):
        """Mark bot start time"""
        self.start_time = datetime.datetime.now()

    def update_price(self, price: float):
        """Update current price"""
        self.current_price = price

    def add_action(self, action: str):
        """Add an action to recent actions list"""
        timestamp = datetime.datetime.now().strftime('%H:%M:%S')
        self.recent_actions.append(f"[{timestamp}] {action}")
        if len(self.recent_actions) > self.max_actions:
            self.recent_actions.pop(0)

    def set_order(self, order_id: int, price: float, quantity: float):
        """Set current order info"""
        self.current_order = {
            'order_id': order_id,
            'price': price,
            'quantity': quantity
        }

    def clear_order(self):
        """Clear current order"""
        self.current_order = None

    def display(self):
        """Display current status (called periodically)"""
        # Clear previous lines and move cursor up
        print("\n" + "=" * 80)
        print(f"🤖 BOT RUNNING - {self.symbol} | ${self.usd_amount:.2f} USD")

        if self.start_time:
            uptime = datetime.datetime.now() - self.start_time
            print(f"⏱️  Uptime: {str(uptime).split('.')[0]}")

        # Current price
        if self.current_price:
            print(f"💰 Current Price: ${self.current_price:.6f}")
        else:
            print(f"💰 Current Price: Loading...")

        # Current order
        if self.current_order:
            print(f"📋 Active Order: ID={self.current_order['order_id']} | "
                  f"Price=${self.current_order['price']:.6f} | "
                  f"Qty={self.current_order['quantity']:.4f}")
        else:
            print(f"📋 Active Order: None")

        # Recent actions
        print(f"\n📊 Recent Actions (last {min(len(self.recent_actions), self.max_actions)}):")
        if self.recent_actions:
            for action in self.recent_actions[-self.max_actions:]:
                print(f"   {action}")
        else:
            print("   (No actions yet)")

        print("=" * 80)
