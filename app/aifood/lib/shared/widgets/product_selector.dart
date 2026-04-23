import 'package:flutter/material.dart';

class ProductSelectorSheet extends StatefulWidget {
  final String title;
  final List<String> allProducts;
  final List<String> selected;
  final Function(List<String>) onSave;

  const ProductSelectorSheet({
    super.key,
    required this.title,
    required this.allProducts,
    required this.selected,
    required this.onSave,
  });

  @override
  State<ProductSelectorSheet> createState() => _ProductSelectorSheetState();
}

class _ProductSelectorSheetState extends State<ProductSelectorSheet> {
  late List<String> _selected;

  @override
  void initState() {
    super.initState();
    _selected = List.from(widget.selected);
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        color: Color(0xFF2A2A2A),
        borderRadius: BorderRadius.only(
          topLeft: Radius.circular(53),
          topRight: Radius.circular(53),
        ),
      ),
      padding: const EdgeInsets.fromLTRB(24, 16, 24, 48),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Планка
          Container(
            width: 80,
            height: 5,
            margin: const EdgeInsets.only(bottom: 20),
            decoration: BoxDecoration(
              color: const Color(0xFFD9D9D9),
              borderRadius: BorderRadius.circular(10),
            ),
          ),

          // Заголовок
          Text(
            widget.title,
            style: const TextStyle(
              fontFamily: 'Idiqlat',
              fontSize: 20,
              fontWeight: FontWeight.w900,
              color: Colors.white,
            ),
          ),
          const SizedBox(height: 16),

          // Список продуктов
          SizedBox(
            height: 300,
            child: ListView.builder(
              itemCount: widget.allProducts.length,
              itemBuilder: (context, index) {
                final product = widget.allProducts[index];
                final isSelected = _selected.contains(product);

                return GestureDetector(
                  onTap: () {
                    setState(() {
                      if (isSelected) {
                        _selected.remove(product);
                      } else {
                        _selected.add(product);
                      }
                    });
                  },
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                      vertical: 14,
                      horizontal: 8,
                    ),
                    decoration: BoxDecoration(
                      border: Border(
                        bottom: BorderSide(
                          color: Colors.white.withOpacity(0.08),
                        ),
                      ),
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text(
                          product,
                          style: const TextStyle(
                            fontFamily: 'Idiqlat',
                            fontSize: 16,
                            color: Colors.white,
                          ),
                        ),
                        if (isSelected)
                          const Icon(
                            Icons.check,
                            color: Colors.white,
                            size: 18,
                          ),
                      ],
                    ),
                  ),
                );
              },
            ),
          ),
          const SizedBox(height: 16),

          // Кнопка сохранить
          SizedBox(
            width: double.infinity,
            height: 52,
            child: ElevatedButton(
              onPressed: () {
                widget.onSave(_selected);
                Navigator.pop(context);
              },
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFF696969),
                overlayColor: const Color(0xFF888888),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(44),
                ),
                elevation: 0,
              ),
              child: const Text(
                'Сохранить',
                style: TextStyle(
                  fontFamily: 'Idiqlat',
                  fontSize: 18,
                  fontWeight: FontWeight.w900,
                  color: Colors.white,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}