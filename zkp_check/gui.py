#!/usr/bin/env python3
"""Interactive interface for the 2x2 block extensibility check.

Compose a 2x2 Shakashaka configuration with the mouse and ask whether it
extends to a valid solution. On unsatisfiable configurations the tool writes
the conflicting constraint instances (extracted from the unsatisfiable core)
to shakashaka_reason.log, next to the DIMACS formula and a DRAT proof.
"""

import tkinter as tk
from tkinter import messagebox, ttk

from block_solver import (ShakashakaSolver, ShakashakaPiece,
                          GUI_TO_SAT, SAT_TO_GUI)

# =============================================================================
# GUI
# =============================================================================

class PieceCanvas(tk.Canvas):
    def __init__(self, parent, piece_type, size=60, **kwargs):
        bg = kwargs.pop('bg', 'white')
        super().__init__(parent, width=size, height=size, bg=bg,
                         highlightthickness=1, highlightbackground='gray', **kwargs)
        self.piece_type = piece_type
        self.size = size
        self.draw_piece()

    def draw_piece(self):
        self.delete("all")
        s = self.size
        m = 2
        pt = self.piece_type
        color = '#404040'

        if pt == ShakashakaPiece.BLACK:
            self.create_rectangle(m, m, s - m, s - m, fill=color)
        elif pt == ShakashakaPiece.K2:
            self.create_polygon(m, m, m, s - m, s - m, s - m, fill=color)
        elif pt == ShakashakaPiece.K3:
            self.create_polygon(s - m, m, m, s - m, s - m, s - m, fill=color)
        elif pt == ShakashakaPiece.K1:
            self.create_polygon(m, m, s - m, m, m, s - m, fill=color)
        elif pt == ShakashakaPiece.K4:
            self.create_polygon(m, m, s - m, m, s - m, s - m, fill=color)


class DraggablePiece(PieceCanvas):
    def __init__(self, parent, piece_type, app, size=60, **kwargs):
        super().__init__(parent, piece_type, size, **kwargs)
        self.app = app
        self.bind("<Button-1>", lambda e: app.start_drag(piece_type))
        self.bind("<B1-Motion>", app.on_drag)
        self.bind("<ButtonRelease-1>", app.end_drag)
        self.configure(cursor="hand2")


class GridCell(PieceCanvas):
    def __init__(self, parent, row, col, size=60, is_input=False, **kwargs):
        super().__init__(parent, ShakashakaPiece.WHITE, size, **kwargs)
        self.row = row
        self.col = col
        self.configure(
            highlightbackground='#2196F3' if is_input else 'black',
            highlightthickness=3 if is_input else 1
        )

    def set_piece(self, piece_type):
        self.piece_type = piece_type
        self.draw_piece()


class SolutionWindow(tk.Toplevel):
    def __init__(self, parent, grid_data, input_row, input_col):
        super().__init__(parent)
        self.title("SAT Solution")
        n = len(grid_data)
        cell_size = min(50, 600 // n)
        window_size = n * cell_size + 60
        self.geometry(f"{window_size}x{window_size}")
        
        frame = tk.Frame(self, bg='white', padx=20, pady=20)
        frame.pack(fill='both', expand=True)
        
        # Center the grid
        grid_frame = tk.Frame(frame, bg='white')
        grid_frame.place(relx=0.5, rely=0.5, anchor='center')
        
        for r in range(n):
            for c in range(n):
                is_input = (input_row <= r <= input_row + 1) and (input_col <= c <= input_col + 1)
                bg_color = '#E3F2FD' if is_input else 'white'
                cell = PieceCanvas(grid_frame, grid_data[r][c], size=cell_size, bg=bg_color)
                cell.grid(row=r, column=c, padx=1, pady=1)


class ShakashakaApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Shakashaka SAT Solver")
        self.root.geometry("700x700")
        self.root.minsize(600, 600)
        
        self.grid_cells = []  # 2x2 input cells
        self.drag_window = None
        self.drag_piece = None
        self.grid_size = tk.IntVar(value=8)
        self.input_row = 3  # Position of 2x2 in the grid (0-indexed)
        self.input_col = 3
        self.dragging_2x2 = False
        self.drag_offset = (0, 0)
        self.setup_ui()

    def setup_ui(self):
        main_frame = tk.Frame(self.root, padx=15, pady=15)
        main_frame.pack(fill='both', expand=True)

        # === Top Controls ===
        controls_frame = tk.Frame(main_frame)
        controls_frame.pack(fill='x', pady=(0, 10))
        
        # Grid size
        tk.Label(controls_frame, text="Grid Size:", font=('Arial', 10)).pack(side='left')
        self.size_slider = tk.Scale(
            controls_frame, from_=5, to=16, orient='horizontal',
            variable=self.grid_size, command=self.on_grid_size_change,
            length=150, showvalue=True
        )
        self.size_slider.pack(side='left', padx=(5, 20))
        
        # Piece palette
        tk.Label(controls_frame, text="Pieces:", font=('Arial', 10)).pack(side='left', padx=(10, 5))
        piece_order = [
            ShakashakaPiece.WHITE,
            ShakashakaPiece.BLACK,
            ShakashakaPiece.K1,
            ShakashakaPiece.K4,
            ShakashakaPiece.K2,
            ShakashakaPiece.K3
        ]
        for piece in piece_order:
            DraggablePiece(controls_frame, piece, self, size=40).pack(side='left', padx=2)
        
        # Solve button
        tk.Button(
            controls_frame, text="SOLVE", command=self.solve, font=('Arial', 11, 'bold'),
            bg='#4CAF50', fg='white', padx=15, pady=5
        ).pack(side='right', padx=10)

        # === Main Grid Canvas ===
        self.canvas_frame = tk.Frame(main_frame, bg='#f0f0f0', relief='sunken', bd=2)
        self.canvas_frame.pack(fill='both', expand=True)
        
        self.canvas = tk.Canvas(self.canvas_frame, bg='#f5f5f5', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True, padx=5, pady=5)
        
        # Bind events for dragging 2x2 block
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.canvas.bind("<Configure>", lambda e: self.draw_grid())
        
        # Initialize 2x2 input data
        self.input_data = [[ShakashakaPiece.WHITE for _ in range(2)] for _ in range(2)]
        
        self.root.after(100, self.draw_grid)

    def on_grid_size_change(self, value=None):
        size = self.grid_size.get()
        max_pos = size - 3
        self.input_row = max(1, min(self.input_row, max_pos))
        self.input_col = max(1, min(self.input_col, max_pos))
        self.draw_grid()

    def get_cell_size(self):
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        size = self.grid_size.get()
        return min((canvas_width - 20) // size, (canvas_height - 20) // size, 60)

    def get_grid_origin(self):
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        size = self.grid_size.get()
        cell_size = self.get_cell_size()
        grid_width = size * cell_size
        grid_height = size * cell_size
        ox = (canvas_width - grid_width) // 2
        oy = (canvas_height - grid_height) // 2
        return ox, oy

    def draw_grid(self):
        self.canvas.delete("all")
        size = self.grid_size.get()
        cell_size = self.get_cell_size()
        ox, oy = self.get_grid_origin()
        
        for r in range(size):
            for c in range(size):
                x1 = ox + c * cell_size
                y1 = oy + r * cell_size
                x2 = x1 + cell_size
                y2 = y1 + cell_size
                
                is_border = (r == 0 or r == size - 1 or c == 0 or c == size - 1)
                is_input = (self.input_row <= r <= self.input_row + 1) and (self.input_col <= c <= self.input_col + 1)
                
                if is_border:
                    fill_color = '#404040'
                    outline_color = '#303030'
                elif is_input:
                    fill_color = '#E3F2FD'
                    outline_color = '#2196F3'
                else:
                    fill_color = 'white'
                    outline_color = '#cccccc'
                
                self.canvas.create_rectangle(x1, y1, x2, y2, fill=fill_color, outline=outline_color, width=2 if is_input else 1)
                
                # Draw pieces
                if is_border:
                    piece_type = ShakashakaPiece.BLACK
                elif is_input:
                    dr = r - self.input_row
                    dc = c - self.input_col
                    piece_type = self.input_data[dr][dc]
                else:
                    piece_type = ShakashakaPiece.WHITE
                
                self.draw_piece_on_canvas(x1, y1, cell_size, piece_type)
        
        # Draw instruction text
        self.canvas.create_text(
            ox + (size * cell_size) // 2, oy - 10,
            text="Drag the blue 2x2 region to position it • Drop pieces onto it",
            font=('Arial', 9), fill='#666666'
        )

    def draw_piece_on_canvas(self, x, y, size, piece_type):
        m = 3
        color = '#404040'
        
        if piece_type == ShakashakaPiece.BLACK:
            self.canvas.create_rectangle(x+m, y+m, x+size-m, y+size-m, fill=color, outline='')
        elif piece_type == ShakashakaPiece.K1:
            self.canvas.create_polygon(x+m, y+m, x+size-m, y+m, x+m, y+size-m, fill=color, outline='')
        elif piece_type == ShakashakaPiece.K2:
            self.canvas.create_polygon(x+m, y+m, x+m, y+size-m, x+size-m, y+size-m, fill=color, outline='')
        elif piece_type == ShakashakaPiece.K3:
            self.canvas.create_polygon(x+size-m, y+m, x+m, y+size-m, x+size-m, y+size-m, fill=color, outline='')
        elif piece_type == ShakashakaPiece.K4:
            self.canvas.create_polygon(x+m, y+m, x+size-m, y+m, x+size-m, y+size-m, fill=color, outline='')

    def get_cell_at(self, canvas_x, canvas_y):
        """Returns (row, col) for a canvas coordinate, or None if outside grid"""
        size = self.grid_size.get()
        cell_size = self.get_cell_size()
        ox, oy = self.get_grid_origin()
        
        col = int((canvas_x - ox) // cell_size)
        row = int((canvas_y - oy) // cell_size)
        
        if 0 <= row < size and 0 <= col < size:
            return row, col
        return None

    def on_canvas_click(self, event):
        cell = self.get_cell_at(event.x, event.y)
        if cell:
            row, col = cell
            # Check if clicking on the 2x2 input region
            if (self.input_row <= row <= self.input_row + 1) and (self.input_col <= col <= self.input_col + 1):
                self.dragging_2x2 = True
                self.drag_offset = (row - self.input_row, col - self.input_col)
                self.canvas.configure(cursor="fleur")

    def on_canvas_drag(self, event):
        if self.dragging_2x2:
            cell = self.get_cell_at(event.x, event.y)
            if cell:
                row, col = cell
                new_row = row - self.drag_offset[0]
                new_col = col - self.drag_offset[1]
                
                size = self.grid_size.get()
                max_pos = size - 3
                new_row = max(1, min(new_row, max_pos))
                new_col = max(1, min(new_col, max_pos))
                
                if new_row != self.input_row or new_col != self.input_col:
                    self.input_row = new_row
                    self.input_col = new_col
                    self.draw_grid()

    def on_canvas_release(self, event):
        self.dragging_2x2 = False
        self.canvas.configure(cursor="")

    def start_drag(self, piece_type):
        self.drag_piece = piece_type
        self.drag_window = tk.Toplevel(self.root)
        self.drag_window.overrideredirect(True)
        self.drag_window.attributes('-topmost', True, '-alpha', 0.7)
        PieceCanvas(self.drag_window, piece_type, size=50).pack()
        self.update_drag()

    def on_drag(self, event):
        self.update_drag()

    def update_drag(self):
        if self.drag_window:
            x = self.root.winfo_pointerx()
            y = self.root.winfo_pointery()
            self.drag_window.geometry(f"+{x - 25}+{y - 25}")

    def end_drag(self, event):
        if self.drag_window:
            self.drag_window.destroy()
            self.drag_window = None
            
            # Get canvas coordinates
            canvas_x = self.canvas.winfo_pointerx() - self.canvas.winfo_rootx()
            canvas_y = self.canvas.winfo_pointery() - self.canvas.winfo_rooty()
            
            cell = self.get_cell_at(canvas_x, canvas_y)
            if cell:
                row, col = cell
                # Check if dropping on the 2x2 input region
                if (self.input_row <= row <= self.input_row + 1) and (self.input_col <= col <= self.input_col + 1):
                    dr = row - self.input_row
                    dc = col - self.input_col
                    self.input_data[dr][dc] = self.drag_piece
                    self.draw_grid()

    def solve(self):
        grid_size = self.grid_size.get()
        
        result = ShakashakaSolver(
            self.input_data, 
            output_n=grid_size,
            input_row=self.input_row,
            input_col=self.input_col
        ,
            debug_files=True
        ).solve()
        
        if result:
            SolutionWindow(self.root, result, self.input_row, self.input_col)
        else:
            messagebox.showwarning(
                "Unsatisfiable",
                "This configuration cannot be extended to a valid solution.\n"
                "See shakashaka_reason.log for the conflicting constraints.")


if __name__ == "__main__":
    root = tk.Tk()
    ShakashakaApp(root)
    root.mainloop()
