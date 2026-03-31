-- Create event pricing table
CREATE TABLE IF NOT EXISTS user_eventpricing (
    id INT AUTO_INCREMENT PRIMARY KEY,
    event_type VARCHAR(100) UNIQUE NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    max_capacity INT NOT NULL DEFAULT 50,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Insert default pricing
INSERT INTO user_eventpricing (event_type, price, max_capacity) VALUES
('Wedding', 5000.00, 50),
('Birthday', 5000.00, 50),
('Christening', 5000.00, 50),
('Conference', 7000.00, 100),
('Corporate Event', 7000.00, 100)
ON DUPLICATE KEY UPDATE 
    price = VALUES(price),
    max_capacity = VALUES(max_capacity);

-- Verify all events are added
SELECT * FROM user_eventpricing ORDER BY event_type;
