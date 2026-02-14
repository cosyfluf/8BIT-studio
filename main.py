import tkinter as tk
from gui_app import RetroMidiApp

def main():
    """Application entry point."""
    root = tk.Tk()
    
    # Initialize the GUI Application
    app = RetroMidiApp(root)
    
    # Safe cleanup on window close
    root.protocol("WM_DELETE_WINDOW", lambda: (
        app.synth.stop_stream(), 
        root.destroy()
    ))
    
    root.mainloop()

if __name__ == "__main__":
    main()