from flask import Flask, render_template, request, redirect, url_for, session, send_file
import pandas as pd
from datetime import datetime
import sqlite3
import io
import os

app = Flask(__name__)
app.secret_key = "inventario_super_seguro_2026"

DB_PATH = "inventario.db"

# ===============================
# CONEXION DB
# ===============================
def get_db():
    return sqlite3.connect(DB_PATH)

# ===============================
# CREAR TABLAS
# ===============================
def crear_db():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS productos(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        categoria TEXT,
        item TEXT,
        descripcion TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS inventario(
        producto TEXT PRIMARY KEY,
        stock INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS movimientos(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT,
        producto TEXT,
        categoria TEXT,
        unidad TEXT,
        cantidad INTEGER,
        tipo TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario TEXT UNIQUE,
        clave TEXT,
        rol TEXT
    )
    """)
    cursor = conn.execute("SELECT * FROM usuarios WHERE usuario='admin'")

    if not cursor.fetchone():
        conn.execute(
            "INSERT INTO usuarios (usuario, clave, rol) VALUES (?, ?, ?)",
            ("admin", "admin123", "admin")
        )

    conn.commit()
    conn.close()

crear_db()

# ===============================
# LOGIN
# ===============================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # Lee con .get() para evitar errores si cambia el name del input
        usuario = request.form.get("usuario")
        clave = request.form.get("clave")

        if not usuario or not clave:
            return render_template("login.html", error="Ingresa usuario y contraseña")

        conn = sqlite3.connect("inventario.db")
        cur = conn.cursor()

        cur.execute(
            "SELECT usuario, clave, rol FROM usuarios WHERE usuario=?",
            (usuario,)
        )
        user = cur.fetchone()
        conn.close()

        # user = (usuario, clave, rol)
        if user and user[1] == clave:
            session["logged_in"] = True
            session["usuario"] = user[0]
            session["rol"] = user[2]

            if session["rol"] == "requerimientos":
                return redirect(url_for("requerimientos"))
            return redirect(url_for("index"))

        return render_template("login.html", error="Usuario o contraseña incorrectos")

    return render_template("login.html")

# ===============================
# GESTION_USUARIOS
# ===============================
@app.route("/gestion_usuarios", methods=["GET","POST"])
def gestion_usuarios():

    if "usuario" not in session or session.get("rol") != "admin":
        return redirect(url_for("index"))

    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":

        accion = request.form.get("accion")

        usuario = request.form.get("usuario")
        clave = request.form.get("clave")
        rol = request.form.get("rol")

        if accion == "crear":
            cur.execute(
                "INSERT INTO usuarios (usuario, clave, rol) VALUES (?,?,?)",
                (usuario, clave, rol)
            )

        elif accion == "eliminar":
            cur.execute(
                "DELETE FROM usuarios WHERE usuario=?",
                (usuario,)
            )

        elif accion == "cambiar_clave":
            cur.execute(
                "UPDATE usuarios SET clave=? WHERE usuario=?",
                (clave, usuario)
            )

        conn.commit()

    cur.execute("SELECT usuario, rol FROM usuarios")
    usuarios = cur.fetchall()

    conn.close()

    return render_template("gestion_usuarios.html", usuarios=usuarios)

# ===============================
# LOGOUT
# ===============================
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ===============================
# INDEX
# ===============================
@app.route("/", methods=["GET","POST"])
def index():

    if not session.get("logged_in"):
        return redirect(url_for("login"))

    if session.get("rol") == "requerimientos":
        return redirect(url_for("requerimientos"))

    conn = get_db()
    cur = conn.cursor()

    # Cargar productos
    df = pd.read_sql_query("SELECT * FROM productos", conn)

    productos_lista = df["item"].tolist()

    productos_info = {
        row["item"]: {
            "categoria": row["categoria"],
            "unidad": row["descripcion"]
        }
        for _, row in df.iterrows()
    }

    # Calcular stock real desde movimientos
    mov_stock = pd.read_sql_query(
        "SELECT producto, tipo, cantidad FROM movimientos", conn
    )

    inventario = {}

    if not mov_stock.empty:
        mov_stock["valor"] = mov_stock.apply(
            lambda row: row["cantidad"] if row["tipo"] == "entrada" else -row["cantidad"],
            axis=1
        )

        mov_stock = mov_stock.sort_index()

    stock_real = {}

    for producto, grupo in mov_stock.groupby("producto"):
        stock = 0

        for val in grupo["valor"]:
            stock = max(0, stock + val)

        stock_real[producto] = stock

    inventario = stock_real

    # Movimientos
    mov_df = pd.read_sql_query("SELECT * FROM movimientos", conn)
    movimientos = mov_df.to_dict("records")

    if request.method == "POST":

      # ===== AGREGAR PRODUCTO =====
        if request.form.get("accion") == "agregar_producto":

            nueva_categoria = request.form["nueva_categoria"].strip().upper()
            nuevo_producto = request.form["nuevo_producto"].strip().upper()
            nueva_unidad = request.form["nueva_unidad"].strip().upper()

            cur.execute("SELECT id FROM productos WHERE item = ?", (nuevo_producto,))
            existe = cur.fetchone()

            if not existe:
                cur.execute("""
                INSERT INTO productos (categoria,item,descripcion)
                VALUES (?,?,?)
                """,(
                    nueva_categoria,
                    nuevo_producto,
                    nueva_unidad
                ))

                conn.commit()

            conn.close()
            return redirect(url_for("index"))

        # ===== MOVIMIENTOS =====
        producto = request.form["producto"]
        cantidad = int(request.form["cantidad"])
        tipo = request.form["tipo"]

        cur.execute("SELECT stock FROM inventario WHERE producto=?", (producto,))
        fila = cur.fetchone()

        stock_actual = fila[0] if fila else 0

        if tipo == "entrada":
            stock_actual += cantidad
        else:
            stock_actual -= cantidad

        # 🔥 evitar negativos
        if stock_actual < 0:
            stock_actual = 0

        cur.execute("""
        INSERT OR REPLACE INTO inventario(producto,stock)
        VALUES (?,?)
        """,(producto,stock_actual))

        info = productos_info.get(producto, {"categoria":"","unidad":""})

        cur.execute("""
        INSERT INTO movimientos(fecha,producto,categoria,unidad,cantidad,tipo)
        VALUES (?,?,?,?,?,?)
        """,(
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            producto,
            info["categoria"],
            info["unidad"],
            cantidad,
            tipo
        ))

        conn.commit()
        conn.close()

        return redirect(url_for("index"))

    categorias_limpias = (
        df["categoria"]
        .astype(str)
        .str.strip()
        .str.upper()
        .unique()
        .tolist()
    )

    categorias = ["Todas"] + sorted(categorias_limpias)

         # ===============================
    # FILTROS GET (REGISTRAR MOVIMIENTO)
    # ===============================
    categoria_filtro = request.args.get("categoria", "Todas").strip().lower()
    buscar = request.args.get("buscar", "").strip().lower()

    productos_filtrados = []

    for p in productos_lista:
        info = productos_info.get(p, {})
        categoria_prod = info.get("categoria", "").strip().lower()

        # Filtro por categoría
        if categoria_filtro != "todas" and categoria_prod != categoria_filtro:
            continue

        # Filtro por búsqueda
        if buscar and buscar not in p.lower():
            continue

        productos_filtrados.append(p)

    productos_lista = productos_filtrados
    # ===============================
    # RENDER
    # ===============================
    return render_template(
        "index.html",
        productos=productos_lista,
        movimientos=movimientos,
        inventario=inventario,
        productos_info=productos_info,
        categorias=categorias,
        categoria_filtro=categoria_filtro.capitalize(),
        buscar=buscar
    )

# ===============================
# ELIMINAR MOVIMIENTO
# ===============================
@app.route("/eliminar_movimiento/<int:idx>", methods=["POST"])
def eliminar_movimiento(idx):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("DELETE FROM movimientos WHERE id=?", (idx,))

    conn.commit()
    conn.close()

    return redirect(url_for("index"))

# ===============================
# ELIMINAR ULTIMO PRODUCTO
# ===============================
@app.route("/eliminar_ultimo_producto", methods=["POST"])
def eliminar_ultimo_producto():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id,item FROM productos ORDER BY id DESC LIMIT 1")
    ultimo = cur.fetchone()

    if ultimo:

        producto = ultimo[1]

        cur.execute("DELETE FROM productos WHERE id=?", (ultimo[0],))
        cur.execute("DELETE FROM inventario WHERE producto=?", (producto,))

        conn.commit()

    conn.close()

    return redirect(url_for("index"))

# ===============================
# RESET INVENTARIO
# ===============================
@app.route("/resetear_inventario", methods=["POST"])
def resetear_inventario():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("DELETE FROM inventario")
    cur.execute("DELETE FROM movimientos")

    conn.commit()
    conn.close()

    return redirect(url_for("index"))

# ===============================
# DESCARGAR MOVIMIENTOS
# ===============================
@app.route("/download_movimientos")
def download_movimientos():

    conn = get_db()
    df = pd.read_sql_query("SELECT * FROM movimientos", conn)
    conn.close()

    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return send_file(output, download_name="movimientos.xlsx", as_attachment=True)

# ===============================
# DESCARGAR STOCK ACTUAL
# ===============================
@app.route("/download_stock")
def download_stock():

    conn = get_db()

    # Traer movimientos completos
    df_mov = pd.read_sql("SELECT producto, tipo, cantidad FROM movimientos", conn)

    conn.close()

    if df_mov.empty:
        return "No hay movimientos registrados"

    # Convertir entradas y salidas en valores matemáticos
    df_mov["valor"] = df_mov.apply(
        lambda row: row["cantidad"] if row["tipo"] == "entrada" else -row["cantidad"],
        axis=1
    )

    # 🔥 Calcular stock secuencial (igual que en el sistema)
    stock_dict = {}

    for producto, grupo in df_mov.groupby("producto"):
        stock = 0

        for val in grupo["valor"]:
            stock = max(0, stock + val)

        stock_dict[producto] = stock

    # Convertir a DataFrame
    df_stock = pd.DataFrame(list(stock_dict.items()), columns=["producto", "Stock"])

    # Solo productos con stock mayor a 0
    df_stock = df_stock[df_stock["Stock"] > 0]

    # Ordenar
    df_stock = df_stock.sort_values("producto")

    # Exportar Excel
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df_stock.to_excel(writer, index=False, sheet_name="Stock Actual")

    output.seek(0)

    return send_file(
        output,
        download_name="Stock_Actual.xlsx",
        as_attachment=True
    )

# ===============================
# REQUERIMIENTOS
# ===============================
@app.route("/requerimientos", methods=["GET","POST"])
def requerimientos():

    if not session.get("logged_in"):
        return redirect(url_for("login"))

    if session.get("rol") not in ["admin","requerimientos"]:
        return redirect(url_for("index"))

    conn = get_db()

    df_prod = pd.read_sql_query("SELECT * FROM productos", conn)
    df_mov = pd.read_sql_query(
        "SELECT producto, tipo, cantidad FROM movimientos", conn
    )
    inventario_dict = {}

    if not df_mov.empty:

        df_mov["valor"] = df_mov.apply(
            lambda row: row["cantidad"] if row["tipo"] == "entrada" else -row["cantidad"],
            axis=1
        )

        # (Si tienes ID o fecha, puedes ordenar aquí)
        # df_mov = df_mov.sort_values("id")

        for producto, grupo in df_mov.groupby("producto"):

            stock = 0

            for val in grupo["valor"]:
                stock = max(0, stock + val)

            inventario_dict[producto] = stock
    productos = []

    for _, row in df_prod.iterrows():

        stock = max(0, inventario_dict.get(row["item"],0))

        productos.append({
            "producto": row["item"],
            "categoria": row["categoria"],
            "unidad": row["descripcion"],
            "stock": stock
        })

    if request.method == "POST":

        solicitante = request.form.get("solicitante")

        data_excel = []

        for p in productos:

            req = request.form.get(f"req_{p['producto']}")

            requerida = int(req) if req and req.isdigit() else 0

            if requerida > 0:

                solicitar = max(0, requerida - p["stock"])

                data_excel.append({
                    "Producto": p["producto"],
                    "Categoria": p["categoria"],
                    "Stock": p["stock"],
                    "Cantidad requerida": requerida,
                    "Cantidad a solicitar": solicitar
                })

        df_excel = pd.DataFrame(data_excel)

        numero = datetime.now().strftime("%Y%m%d%H%M%S")

        output = io.BytesIO()

        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df_excel.to_excel(writer, index=False, startrow=3)

            ws = writer.sheets["Sheet1"]

            ws.write("A1", f"REQUERIMIENTO N° {numero}")
            ws.write("A2", f"Solicitante: {solicitante}")
            ws.write("A3", f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

        output.seek(0)

        return send_file(output, download_name=f"requerimiento_{numero}.xlsx", as_attachment=True)

    return render_template("requerimientos.html", productos=productos)

if __name__ == "__main__":
    app.run(debug=True)
