import bcrypt

password = 'owner#2005'
password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')
print(password_hash)