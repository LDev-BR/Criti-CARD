import os
import re
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image
from dotenv import load_dotenv
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY")
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['CAPA_FOLDER'] = 'static/cards'
app.config['MAX_CONTENT_LENGTH'] = 3 * 1024 * 1024 
load_dotenv()
EXTENSOES = {'png', 'jpg', 'jpeg', 'gif'}
DATABASE = 'criticard.db'
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db
@app.teardown_appcontext
def fechar_conexao(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def username_valido(username):
    return re.match(r'^[a-zA-Z0-9_-]{3,15}$', username) is not None
def imagem_valida(arquivo):
    if not ('.' in arquivo.filename and arquivo.filename.rsplit('.', 1)[1].lower() in EXTENSOES):
        return False
    try:
        img = Image.open(arquivo)
        img.verify()
        arquivo.seek(0)
        return True
    except Exception:
        return False
def email_valido(email):
    padrao = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    return re.match(padrao, email) is not None
def senha_forte(senha):
    return re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%&_*])[A-Za-z\d!@#$%&_*]{8,}$', senha) is not None

def inicializar_banco():
    with app.app_context():
        db = get_db()
        db.execute('''
            CREATE TABLE IF NOT EXISTS usuarios(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                nome TEXT NOT NULL,
                apelido TEXT NOT NULL,
                imagem TEXT,
                about TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                senha TEXT NOT NULL,
                admin INTEGER DEFAULT 0
            );
        ''') 
        db.execute('''
            CREATE TABLE IF NOT EXISTS cards(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                capa TEXT NOT NULL,
                sobre TEXT NOT NULL,
                nota INTEGER NOT NULL,
                card_id INTEGER NOT NULL,
                FOREIGN KEY (card_id) REFERENCES usuarios (id)
            );
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS contatos(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                email TEXT NOT NULL,
                mensagem TEXT NOT NULL
                );
        ''')
        db.commit()
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        username = request.form['username'].upper()
        senha = request.form['senha']
        db = get_db()
        usuario = db.execute('SELECT * FROM usuarios WHERE username=? OR email=?',
                            (username, username.lower())).fetchone()
        if usuario and check_password_hash(usuario['senha'], senha):
            session['usuario_id'] = usuario['id']
            session['user_nome'] = usuario['username']
            session['user_admin'] = usuario['admin']
            session['user_senha'] = usuario['senha']
            return redirect(url_for('dashboard'))
        else:
            flash('Usuário ou senha inválidos.')
            return render_template('index.html')
    return render_template('index.html')

@app.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    if request.method == 'POST':
        username = request.form['username'].upper()
        nome = request.form['nome']
        imagem = request.files['imagem']
        apelido = request.form['apelido']
        about = request.form['about']
        email = request.form['email'].lower()
        senha = request.form['senha']
        nome_arquivo = None
        if not username_valido(username):
            flash('Nome de usuário inválido, (3 a 15 caracteres).')
            return render_template('cadastro.html')
        if imagem and imagem_valida(imagem):
            nome_arquivo = secure_filename(imagem.filename)
            imagem.save(os.path.join(app.config['UPLOAD_FOLDER'], nome_arquivo))
        if not email_valido(email):
            flash('E-mail inválido.')
            return render_template('cadastro.html')
        if not senha_forte(senha):
            flash('A senha deve ter pelo menos 8 caracteres, incluindo letras maiusculas, minusculas, números e caracteres especiais.')
            return render_template('cadastro.html')
        senha_segura = generate_password_hash(senha)
        db = get_db()
        try:
            db.execute('INSERT INTO usuarios (username, nome, apelido, imagem, about, email, senha) VALUES (?, ?, ?, ?, ?, ?, ?)', (username, nome, apelido, nome_arquivo, about, email, senha_segura))
            db.commit()
            flash('Usuário cadastrado com sucesso!!!')
            return redirect(url_for('index'))
        except sqlite3.IntegrityError:
            flash('Usuário já cadastrado')
            return render_template('cadastro.html')
    return render_template('cadastro.html')

@app.route('/cadastro_cards', methods=['GET', 'POST'])
def cadastro_cards():
    if 'usuario_id' not in session:
        flash('Logue-se para continuar!')
        return redirect(url_for('index'))
    if request.method == 'POST':
        titulo = request.form['titulo'].upper()
        capa = request.files['capa']
        sobre = request.form['sobre']
        nota = request.form['nota']
        nome_card = None
        if capa and imagem_valida(capa):
            nome_card = secure_filename(capa.filename)
            capa.save(os.path.join(app.config['CAPA_FOLDER'], nome_card))
        db = get_db()
        try:
            db.execute('INSERT INTO cards (titulo, capa, sobre, nota, card_id) VALUES (?, ?, ?, ?, ?)', (titulo, nome_card, sobre, nota, session['usuario_id']))
            db.commit()
            flash('Card criado com sucesso!!!')
            return redirect(url_for('dashboard'))
        except sqlite3.IntegrityError:
            flash('Erro ao criar o card, tente novamente.')
    return render_template('cadastro_cards.html')

@app.route('/dashboard')
def dashboard():
    if 'usuario_id' not in session:
        flash('Logue-se para continuar!')
        return redirect(url_for('index'))
    db = get_db()
    usuario = db.execute('SELECT * FROM usuarios WHERE id=?', (session['usuario_id'],)).fetchone()
    card = db.execute('''
        SELECT id, titulo, capa, sobre, nota, card_id 
        FROM cards
        WHERE card_id = ?
    ''', (session['usuario_id'],)).fetchall()
    return render_template('dashboard.html', usuario=usuario, card=card)

@app.route('/delete', methods=['GET', 'POST'])
def delete():
    if request.method == 'POST':
        username_dl = request.form['dlun']
        senha_dl = request.form['dlsn']
        db = get_db()
        usuario = db.execute('SELECT * FROM usuarios WHERE username=? OR email=?',(username_dl.upper(), username_dl.lower())).fetchone()
        if usuario and check_password_hash(usuario['senha'], senha_dl):
            db.execute('DELETE FROM cards WHERE card_id = ?', (usuario['id'],))
            db.execute('DELETE FROM usuarios WHERE id=?', (usuario['id'],))
            db.commit()
            flash('Usuário deletado com sucesso.')
            return redirect(url_for('index'))
        else:
            flash('Usuário ou senha inválidos.')
            return render_template('delete.html')
    return render_template('delete.html')

@app.route('/mensagem', methods=['GET', 'POST'])
def mensagem():
    if request.method == 'POST':
        nome = request.form['nome']
        email = request.form['email']
        mensagem = request.form['mensagem']
        try:
            with get_db() as db:
                db.execute('INSERT INTO contatos (nome, email, mensagem) VALUES (?, ?, ?)', (nome, email, mensagem))
                db.commit()
                flash('Mensagem enviada com sucesso!!!')
                return redirect(url_for('dashboard'))
        except sqlite3.IntegrityError:
            flash('Erro ao enviar mensagem.')
            return render_template('dashboard.html')
    return render_template('dashboard.html')

@app.route('/edit', methods=['GET', 'POST'])
def edit():
    if 'usuario_id' not in session:
        flash('Logue-se para continuar!')
        return redirect(url_for('index'))
    db = get_db()
    usuario = db.execute('SELECT * FROM usuarios WHERE id=?', (session['usuario_id'],)).fetchone()
    if request.method == 'POST':
        username = request.form['username'].upper()
        nome = request.form['nome']
        imagem = request.files['imagem']
        apelido = request.form['apelido']
        about = request.form['about']
        email = request.form['email']
        nome_arquivo = usuario['imagem']
        if not username_valido(username):
            flash('Nome de usuário inválido, (3 a 15 caracteres).')
            return render_template('edit.html')
        if imagem and imagem_valida(imagem):
            nome_arquivo = secure_filename(imagem.filename)
            imagem.save(os.path.join(app.config['UPLOAD_FOLDER'], nome_arquivo))
        if not email_valido(email):
            flash('E-mail inválido.')
            return render_template('edit.html')
        try:
                db.execute('UPDATE usuarios SET username=?, nome=?, apelido=?, imagem=?, about=?, email=? WHERE id=?', (username, nome, apelido, nome_arquivo, about, email, usuario['id']))
                db.commit()
                flash('Usuário alterado com sucesso!!!')
                return redirect(url_for('dashboard'))
        except sqlite3.IntegrityError:
                flash('Usuário já cadastrado')
                return render_template('edit.html')
    return render_template('edit.html', usuario=usuario)

@app.route('/deletar_card/<int:id>')
def deletar_card(id):
    db = get_db()
    db.execute('DELETE FROM cards WHERE id = ?', (id,))
    db.commit()
    return redirect(url_for('dashboard'))

@app.route('/excluir_user', methods=['GET', 'POST'])
def excluir():
    if 'usuario_id' not in session:
        flash('Logue-se para continuar!')
        return redirect(url_for('index'))
    db = get_db()
    user = db.execute('SELECT * FROM usuarios WHERE id=?', (session['usuario_id'],)).fetchone()
    if request.method == 'POST':
        username = request.form['username'].upper()
        senha = request.form['senha']
        usuario = db.execute('SELECT * FROM usuarios WHERE username=? OR email=?', (username, username.lower())).fetchone()
        if usuario and check_password_hash(usuario['senha'], senha):
            db.execute('DELETE FROM cards WHERE card_id = ?', (usuario['id'],))
            db.execute('DELETE FROM usuarios WHERE id=?', (usuario['id'],))
            db.commit()
            flash('Usuário excluido com sucesso.')
            return redirect(url_for('index'))
        else:
            flash('Usuário ou senha inválidos.')
            return render_template('excluir.html')
    return render_template('excluir.html', user=user)

@app.route('/admin_excluir', methods=['GET', 'POST'])
def admin_excluir():
    if 'usuario_id' not in session:
        flash('Logue para continuar')
        return redirect(url_for('index'))
    if session.get('user_admin') != 1:
        flash('Função exclusiva de adms!!!')
        return redirect(url_for('index'))
    db = get_db()
    if request.method == 'POST':
        username = request.form['username']
        senha = request.form['senha']
        if username.upper() != session.get('user_nome'):
            usuario = db.execute('SELECT * FROM usuarios WHERE username=? OR email=?', (username.upper(), username.lower())).fetchone()
            if usuario and check_password_hash(session['user_senha'], senha):
                db.execute('DELETE FROM cards WHERE card_id = ?', (usuario['id'],))
                db.execute('DELETE FROM usuarios WHERE id=?', (usuario['id'],))
                db.commit()
                flash('Usuário excluido com sucesso.')
                return redirect(url_for('admin_excluir'))
            else:
                flash('Usuário ou senha inválidos.')
                return render_template('admin_excluir.html')
        else:
            flash('O ADM não pode ser excluido!!!')
            return render_template('dashboard.html')
    return render_template('admin_excluir.html')

@app.route('/listar_mensagens')
def listar_mensagens():
    if 'usuario_id' not in session:
        flash('Logue para continuar')
        return redirect(url_for('index'))
    if session.get('user_admin') != 1:
        flash('Função exclusiva de adms!!!')
        return redirect(url_for('index'))
    db = get_db()
    mensagens = db.execute('SELECT * FROM contatos').fetchall()
    return render_template('admin_mensagens.html', mensagens=mensagens)

@app.route('/listar_users')
def listar_users():
    if 'usuario_id' not in session:
        flash('Logue para continuar')
        return redirect(url_for('index'))
    if session.get('user_admin') != 1:
        flash('Função exclusiva de adms!!!')
        return redirect(url_for('index'))
    db = get_db()
    users = db.execute('SELECT * FROM usuarios').fetchall()
    return render_template('admin_users.html', users=users)

@app.route('/logout')
def logout():
    session.pop('usuario_id', None)
    return redirect(url_for('index'))

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['CAPA_FOLDER'], exist_ok=True)
    inicializar_banco()
    with app.app_context():
        db = get_db()
        admin =  db.execute('SELECT * FROM usuarios where admin=1').fetchall()
        if not admin:
                adm_username = os.getenv("ADM_USERNAME")
                adm_senha = os.getenv("ADM_SENHA")
                senha_adm = generate_password_hash(adm_senha)
                db.execute('INSERT INTO usuarios (username, nome, apelido, about, email, senha, admin) VALUES (?, ?, ?, ?, ?, ?, 1)', (adm_username,'Luis' ,'ADM', 'ADM DO SITE', 'ldev@gmail.com', senha_adm))
                db.commit()
    app.run(debug=True)