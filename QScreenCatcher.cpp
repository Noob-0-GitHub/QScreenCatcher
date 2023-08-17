#include <windows.h>
#include <string>
#include <cstdlib>

int main()
{
  FreeConsole();

  std::string command = ".\\python3.11.1\\Scripts\\pythonw.exe .\\main.py";

  int len = MultiByteToWideChar(CP_ACP, 0, command.c_str(), -1, NULL, 0);
  wchar_t *wcommand = new wchar_t[len];
  MultiByteToWideChar(CP_ACP, 0, command.c_str(), -1, wcommand, len);

  STARTUPINFO si;
  PROCESS_INFORMATION pi;

  ZeroMemory(&si, sizeof(si));
  si.cb = sizeof(si);
  ZeroMemory(&pi, sizeof(pi));

  if (!CreateProcess(NULL, (LPSTR)command.c_str(), NULL, NULL, FALSE, 0, NULL, NULL, &si, &pi))
  {
    return 1;
  }

  WaitForSingleObject(pi.hProcess, INFINITE);

  CloseHandle(pi.hProcess);
  CloseHandle(pi.hThread);

  delete[] wcommand;

  return 0;
}