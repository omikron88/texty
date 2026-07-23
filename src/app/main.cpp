#include "core/machine.hpp"
#include <iostream>

int main() {
    fk1::Machine machine;
    std::cout << "FK1 emulator skeleton initialized at tick " << machine.now() << '\n';
    return 0;
}
