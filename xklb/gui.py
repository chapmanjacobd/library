from tkinter import PhotoImage, Tk
from tkinter.ttk import Button, Frame, Label, Style
from typing import Tuple

import screeninfo

from xklb.utils import log


class UserQuit(BaseException):
    pass


class MrSuperDialogue:
    def quit(self):
        raise UserQuit

    def keep(self):
        self.action = "KEEP"
        self.root.destroy()

    def delete(self):
        self.action = "DELETE"
        self.root.destroy()

    def move_window(self, window_width=200, window_height=180):
        self.root.wm_attributes("-alpha", 0)
        self.root.geometry("{}x{}+{}+{}".format(window_width, window_height, 0, 0))
        self.root.update_idletasks()

        log.info(
            {
                "winfo_root_x": self.root.winfo_x(),
                "winfo_root_y": self.root.winfo_y(),
                "winfo_screen": self.root.winfo_screen(),
                "wm_maxsize": self.root.wm_maxsize(),
            }
        )

        # TODO: Get the screen which contains the Tk Frame
        # current_screen = self.get_monitor_from_coord(self.winfo_x(), self.winfo_y())
        # current_screen.name

        s_width = self.root.winfo_screenwidth()
        s_height = self.root.winfo_screenheight()
        x_cordinate = int((s_width / 2) - (window_width / 2))
        y_cordinate = int((s_height / 2) - (window_height / 2))
        self.root.geometry("{}x{}+{}+{}".format(window_width, window_height, x_cordinate, y_cordinate))
        self.root.wm_attributes("-alpha", 1)

    def __init__(self, path, qty):
        self.root = Tk()
        self.root.title("Library dialogue")

        def callback_error(self, *args):
            raise Exception(*args)

        Tk.report_callback_exception = callback_error

        style = Style(self.root)
        style.theme_use("clam")

        photo = PhotoImage(file="assets/kotobago.png")
        self.root.wm_iconphoto(False, photo)
        self.root.wm_attributes("-topmost", 1)

        for keyseq in ["<Escape>", "<Control-c>", "<Control-q>"]:
            self.root.bind(keyseq, lambda ev: self.quit())

        # menu left
        self.menu_left = Frame(self.root, width=150)
        self.menu_left_upper = Frame(self.menu_left, width=150, height=150)
        self.menu_left_lower = Frame(self.menu_left, width=150)

        keep_btn = Button(self.menu_left_upper, text="Keep", command=self.keep, cursor="heart")
        keep_btn.bind("<Return>", lambda ev: self.keep())
        keep_btn.grid()

        del_btn = Button(self.menu_left_lower, text="Delete", command=self.delete, cursor="spraycan")
        del_btn.bind("<Return>", lambda ev: self.delete())
        del_btn.focus()
        del_btn.grid()

        self.menu_left_upper.pack(side="top", fill="both", expand=True)
        self.menu_left_lower.pack(side="top", fill="both", expand=True)

        # title
        self.some_title_frame = Frame(self.root)
        self.some_title = Label(self.some_title_frame, text="Keep or Delete?")
        self.some_title.pack()

        self.message = Label(self.root, text=f"Keep {path}?", wraplength=180, justify="center")
        self.message.grid(row=1, column=1)

        # status bar
        self.status_frame = Frame(self.root)
        self.status = Label(self.status_frame, text=f"{qty} media to go")
        self.status.pack(fill="both", expand=True)

        self.menu_left.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.some_title_frame.grid(row=0, column=1, sticky="ew")
        self.message.grid(row=1, column=1, sticky="nsew")
        self.status_frame.grid(row=2, column=0, columnspan=2, sticky="ew")

        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(1, weight=1)

        for keyseq in ["<Delete>", "d", "n", "1"]:
            self.root.bind(keyseq, lambda ev: self.delete())
        for keyseq in ["k", "y", "2"]:
            self.root.bind(keyseq, lambda ev: self.keep())

        self.move_window()
        self.root.mainloop()

    @staticmethod
    def get_coord_offset_from_monitor(monitor_name) -> Tuple[int, int]:
        # TODO: assuming screeninfo returns monitors in the same order that Tk is expecting it should
        # be possible to figure out where the monitor sits in the framebuffer then add up the preceding
        # monitors to find the pixel offset within the framebuffer for the window to show up in
        # that monitor but I have some doubts about whether this will work at all as well as
        # the portability of this solution. I cycle through five different monitors throughout
        # the day but I never use more than one simultaneously so I will stop over-optimizing here:
        raise NotImplementedError

    @staticmethod
    def get_monitor_from_coord(x, y):
        monitors = screeninfo.get_monitors()

        for m in reversed(monitors):
            if m.x <= x <= m.width + m.x and m.y <= y <= m.height + m.y:
                return m
        return monitors[0]


def askkeep(path, qty):
    ex = MrSuperDialogue(path, qty)
    return ex.action


if __name__ == "__main__":
    print(askkeep(r"\\supercali\fragil/istic/expiali//docious.exe", 3))